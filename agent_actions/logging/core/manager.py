"""Singleton event manager for centralized event dispatching."""

from __future__ import annotations

import atexit
import contextvars
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

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
    """Singleton event dispatcher that routes events to registered handlers."""

    _instance: EventManager | None = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the event manager; prefer get() for singleton access."""
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
        """Get the singleton EventManager instance (thread-safe)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (for testing)."""
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
        """Register an event handler."""
        with self._fire_lock:
            self._handlers.append(handler)

    def unregister(self, handler: EventHandler) -> None:
        """Unregister an event handler."""
        with self._fire_lock:
            if handler in self._handlers:
                self._handlers.remove(handler)

    def clear_handlers(self) -> None:
        """Remove all registered handlers."""
        with self._fire_lock:
            self._handlers.clear()

    def add_filter(self, filter_: EventFilter) -> None:
        """Add a global event filter applied before handlers."""
        with self._fire_lock:
            self._filters.append(filter_)

    def set_context(self, **kwargs: Any) -> None:
        """Set shared context values injected into event metadata."""
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
        """Get a context value, checking thread-local overlay then global context."""
        with self._fire_lock:
            return self._effective_context().get(key, default)

    def clear_context(self) -> None:
        """Clear all context values."""
        with self._fire_lock:
            self._context.clear()

    @contextmanager
    def context(self, **kwargs: Any) -> Iterator[None]:
        """Temporarily overlay context values; thread-safe and nestable."""
        previous = self._context_overlay.get()
        merged = dict(previous) if previous else {}
        merged.update(kwargs)
        token = self._context_overlay.set(merged)
        try:
            yield
        finally:
            self._context_overlay.reset(token)

    def fire(self, event: BaseEvent) -> None:
        """Fire an event: inject context, apply filters, dispatch to handlers."""
        with self._fire_lock:
            context = self._effective_context()
            handlers = list(self._handlers)
            filters = list(self._filters)

        if context.get("invocation_id"):
            event.meta.invocation_id = context["invocation_id"]
        if context.get("correlation_id"):
            event.meta.correlation_id = context["correlation_id"]

        for key, value in context.items():
            if key not in ("invocation_id", "correlation_id"):
                event.meta.extra[key] = value

        filtered_event: BaseEvent | None = event
        for filter_ in filters:
            if filtered_event is None:
                return
            filtered_event = filter_.filter(filtered_event)

        if filtered_event is None:
            return

        for handler in handlers:
            try:
                if handler.accepts(filtered_event):
                    handler.handle(filtered_event)
            except Exception:
                # Don't let handler errors break the application
                _stdlib_logger.warning("Event handler %s failed", handler, exc_info=True)

    def flush(self) -> None:
        """Flush all handlers, ensuring buffered events are written."""
        with self._fire_lock:
            handlers = list(self._handlers)
        for handler in handlers:
            try:
                handler.flush()
            except Exception:
                _stdlib_logger.warning("Flush failed for handler %s", handler, exc_info=True)


def get_manager() -> EventManager:
    """Get the global EventManager instance."""
    return EventManager.get()


def fire_event(event: BaseEvent) -> None:
    """Fire an event to the global EventManager."""
    EventManager.get().fire(event)
