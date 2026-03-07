"""
Event manager for centralized event dispatching.

The EventManager is a singleton that receives all events via fire_event()
and routes them to registered handlers. This is the central hub of the
logging system.
"""

from __future__ import annotations

import atexit
import contextvars
import logging
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

# Use a non-propagating logger to avoid re-entering EventManager.fire()
# via LoggingBridgeHandler when a handler fails. Messages go directly
# to stderr via lastResort.
_stdlib_logger = logging.getLogger(__name__)
_stdlib_logger.propagate = False

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent
    from agent_actions.logging.core.protocols import EventFilter, EventHandler

# Module-level atexit function registered once.  Delegates to the current
# singleton so that reset() + get() does not accumulate callbacks.
_atexit_registered = False


def _atexit_flush() -> None:
    """Flush the current EventManager singleton (if any) at interpreter exit."""
    if EventManager._instance is not None:
        EventManager._instance.flush()


class EventManager:
    """
    Singleton event dispatcher.

    The EventManager maintains a registry of handlers and dispatches events
    to all handlers that accept them. It also manages shared context
    (invocation_id, correlation_id) that gets injected into all events.

    Usage:
        manager = EventManager.get()
        manager.register(ConsoleHandler())
        manager.set_context(invocation_id="abc123")

        # From anywhere in the app:
        fire_event(MyEvent(message="Hello"))
    """

    _instance: EventManager | None = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the event manager. Use get() instead of direct instantiation."""
        global _atexit_registered

        self._handlers: list[EventHandler] = []
        self._filters: list[EventFilter] = []
        self._context: dict[str, Any] = {}
        self._initialized: bool = False
        self._fire_lock: threading.RLock = threading.RLock()

        # Per-thread/coroutine context overlay set by context().
        # Each thread sees its own value; global context from set_context()
        # is merged underneath.
        self._context_overlay: contextvars.ContextVar[dict[str, Any] | None] = (
            contextvars.ContextVar("_context_overlay", default=None)
        )

        # Register the module-level atexit callback exactly once
        if not _atexit_registered:
            atexit.register(_atexit_flush)
            _atexit_registered = True

    @classmethod
    def get(cls) -> EventManager:
        """
        Get the singleton EventManager instance.

        Thread-safe lazy initialization.

        Returns:
            The global EventManager instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """
        Reset the singleton instance.

        Primarily used for testing. Flushes existing handlers before reset.
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance.flush()
                cls._instance._handlers.clear()
                cls._instance._filters.clear()
                cls._instance._context.clear()
                cls._instance._initialized = False
            cls._instance = None

    def initialize(self) -> None:
        """Mark the manager as initialized after handlers are registered."""
        self._initialized = True

    @property
    def is_initialized(self) -> bool:
        """Check if the manager has been initialized with handlers."""
        return self._initialized

    def register(self, handler: EventHandler) -> None:
        """
        Register an event handler.

        Handlers receive events that pass their accepts() filter.

        Args:
            handler: Handler implementing the EventHandler protocol
        """
        with self._fire_lock:
            self._handlers.append(handler)

    def unregister(self, handler: EventHandler) -> None:
        """
        Unregister an event handler.

        Args:
            handler: Handler to remove
        """
        with self._fire_lock:
            if handler in self._handlers:
                self._handlers.remove(handler)

    def clear_handlers(self) -> None:
        """
        Remove all registered handlers.

        Used by LoggerFactory when re-initializing with force=True
        to prevent handler accumulation.
        """
        with self._fire_lock:
            self._handlers.clear()

    def add_filter(self, filter_: EventFilter) -> None:
        """
        Add a global event filter.

        Filters are applied to all events before they reach handlers.
        If any filter returns None, the event is dropped.

        Args:
            filter_: Filter implementing the EventFilter protocol
        """
        with self._fire_lock:
            self._filters.append(filter_)

    def set_context(self, **kwargs: Any) -> None:
        """
        Set shared context values.

        Context values are automatically injected into event metadata.
        Common context: invocation_id, correlation_id, workflow_name.

        Args:
            **kwargs: Key-value pairs to add to context
        """
        with self._fire_lock:
            self._context.update(kwargs)

    def _effective_context(self) -> dict[str, Any]:
        """Return global context merged with the thread-local overlay.

        Must be called under ``_fire_lock``.
        """
        overlay = self._context_overlay.get()
        if overlay is None:
            return dict(self._context)
        merged = dict(self._context)
        merged.update(overlay)
        return merged

    def get_context(self, key: str, default: Any = None) -> Any:
        """
        Get a context value.

        Checks the thread-local overlay first (set by ``context()``),
        then falls back to the global context (set by ``set_context()``).

        Args:
            key: Context key to retrieve
            default: Default value if key not found

        Returns:
            The context value or default
        """
        with self._fire_lock:
            return self._effective_context().get(key, default)

    def clear_context(self) -> None:
        """Clear all context values."""
        with self._fire_lock:
            self._context.clear()

    @contextmanager
    def context(self, **kwargs: Any) -> Iterator[None]:
        """
        Temporarily set context values within a scope.

        Uses ``contextvars.ContextVar`` so each thread (and each asyncio
        task) gets its own overlay that does not interfere with other
        threads.  Nesting is supported: inner overlays inherit the outer
        overlay's values.

        Example:
            with manager.context(correlation_id="req-123"):
                fire_event(MyEvent(...))  # Gets correlation_id injected

        Args:
            **kwargs: Temporary context values
        """
        previous = self._context_overlay.get()
        merged = dict(previous) if previous else {}
        merged.update(kwargs)
        token = self._context_overlay.set(merged)
        try:
            yield
        finally:
            self._context_overlay.reset(token)

    def fire(self, event: BaseEvent) -> None:
        """
        Fire an event to all registered handlers.

        This is the main entry point for event dispatch. It:
        1. Injects context into event metadata
        2. Applies global filters
        3. Dispatches to handlers that accept the event

        Args:
            event: The event to fire
        """
        # Snapshot mutable state under lock so concurrent register/set_context
        # calls cannot break iteration.
        with self._fire_lock:
            context = self._effective_context()
            handlers = list(self._handlers)
            filters = list(self._filters)

        # Inject context into event metadata
        if context.get("invocation_id"):
            event.meta.invocation_id = context["invocation_id"]
        if context.get("correlation_id"):
            event.meta.correlation_id = context["correlation_id"]

        # Copy extra context into meta
        for key, value in context.items():
            if key not in ("invocation_id", "correlation_id"):
                event.meta.extra[key] = value

        # Apply global filters
        filtered_event: BaseEvent | None = event
        for filter_ in filters:
            if filtered_event is None:
                return
            filtered_event = filter_.filter(filtered_event)

        if filtered_event is None:
            return

        # Dispatch to handlers
        for handler in handlers:
            try:
                if handler.accepts(filtered_event):
                    handler.handle(filtered_event)
            except Exception:
                # Don't let handler errors break the application
                _stdlib_logger.warning("Event handler %s failed", handler, exc_info=True)

    def flush(self) -> None:
        """
        Flush all handlers.

        Ensures all buffered events are written. Called automatically
        at program exit.
        """
        with self._fire_lock:
            handlers = list(self._handlers)
        for handler in handlers:
            try:
                handler.flush()
            except Exception:
                _stdlib_logger.warning("Flush failed for handler %s", handler, exc_info=True)


def get_manager() -> EventManager:
    """
    Get the global EventManager instance.

    Convenience function equivalent to EventManager.get().

    Returns:
        The global EventManager instance
    """
    return EventManager.get()


def fire_event(event: BaseEvent) -> None:
    """
    Fire an event to the global EventManager.

    This is the primary entry point for firing events throughout the application.
    It's a convenience wrapper around EventManager.get().fire().

    Example:
        from agent_actions.logging.core import fire_event

        fire_event(WorkflowStarted(workflow_name="my_workflow"))

    Args:
        event: The event to fire
    """
    EventManager.get().fire(event)
