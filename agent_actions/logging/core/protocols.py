"""
Protocol definitions for event handlers.

Using Protocol (structural subtyping) instead of abstract base classes
allows for more flexible handler implementations without inheritance.
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent, EventLevel


@runtime_checkable
class EventHandler(Protocol):
    """
    Protocol for event handlers.

    Implement this protocol to create custom event handlers.
    Handlers receive events and process them (log to console, file, etc.).

    Example:
        class MyHandler:
            def handle(self, event: BaseEvent) -> None:
                print(f"[{event.level.value}] {event.message}")

            def accepts(self, event: BaseEvent) -> bool:
                return event.level != EventLevel.DEBUG

            def flush(self) -> None:
                pass

        # Usage
        manager.register(MyHandler())  # Works because it implements the protocol
    """

    def handle(self, event: "BaseEvent") -> None:
        """
        Process an event.

        This method is called for every event that passes the accepts() filter.
        Implementations should be fast and non-blocking.

        Args:
            event: The event to process
        """
        ...

    def accepts(self, event: "BaseEvent") -> bool:
        """
        Filter events this handler should process.

        Return True to handle the event, False to skip it.
        This allows handlers to only process certain event types or levels.

        Args:
            event: The event to check

        Returns:
            True if this handler should process the event
        """
        ...

    def flush(self) -> None:
        """
        Flush any buffered output.

        Called when the application is shutting down or when immediate
        output is required. Implementations should ensure all pending
        events are written.
        """
        ...


@runtime_checkable
class EventFilter(Protocol):
    """
    Protocol for event filters.

    Filters can transform or drop events before they reach handlers.
    """

    def filter(self, event: "BaseEvent") -> "BaseEvent | None":
        """
        Filter or transform an event.

        Args:
            event: The event to filter

        Returns:
            The event (possibly modified), or None to drop it
        """
        ...


class LevelFilter:
    """
    Filter events by minimum level.

    Events below the minimum level are dropped.
    """

    def __init__(self, min_level: "EventLevel") -> None:
        self.min_level = min_level

    def filter(self, event: "BaseEvent") -> "BaseEvent | None":
        from agent_actions.logging.core.events import EventLevel

        level_order = [EventLevel.DEBUG, EventLevel.INFO, EventLevel.WARN, EventLevel.ERROR]
        if level_order.index(event.level) >= level_order.index(self.min_level):
            return event
        return None


class CategoryFilter:
    """
    Filter events by category.

    Only events matching the specified categories are passed through.
    """

    def __init__(self, categories: set[str]) -> None:
        self.categories = categories

    def filter(self, event: "BaseEvent") -> "BaseEvent | None":
        if event.category in self.categories:
            return event
        return None
