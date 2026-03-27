"""Protocol definitions for event handlers."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent, EventLevel


@runtime_checkable
class EventHandler(Protocol):
    """Protocol for event handlers that receive and process events."""

    def handle(self, event: "BaseEvent") -> None:
        """Process an event that passed the accepts() filter."""
        ...

    def accepts(self, event: "BaseEvent") -> bool:
        """Return True if this handler should process the event."""
        ...

    def flush(self) -> None:
        """Flush any buffered output."""
        ...

    def close(self) -> None:
        """Close the handler and release resources."""
        ...


@runtime_checkable
class EventFilter(Protocol):
    """Protocol for event filters that can transform or drop events."""

    def filter(self, event: "BaseEvent") -> "BaseEvent | None":
        """Return the event (possibly modified) or None to drop it."""
        ...


class LevelFilter:
    """Filter that drops events below a minimum severity level."""

    def __init__(self, min_level: "EventLevel") -> None:
        self.min_level = min_level

    def filter(self, event: "BaseEvent") -> "BaseEvent | None":
        from agent_actions.logging.core.events import EventLevel

        level_order = EventLevel.ordered()
        if level_order.index(event.level) >= level_order.index(self.min_level):
            return event
        return None


class CategoryFilter:
    """Filter that only passes events matching specified categories."""

    def __init__(self, categories: set[str]) -> None:
        self.categories = categories

    def filter(self, event: "BaseEvent") -> "BaseEvent | None":
        if event.category in self.categories:
            return event
        return None
