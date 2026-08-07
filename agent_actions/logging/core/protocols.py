"""Protocol definitions for event handlers."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent


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
