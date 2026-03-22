"""Console event handler for user-facing output."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent, EventLevel

from agent_actions.logging.core._compat import RICH_AVAILABLE, Console


class ConsoleEventHandler:
    """Handler that outputs events to the console with optional Rich formatting."""

    def __init__(
        self,
        min_level: EventLevel | None = None,
        show_timestamp: bool = True,
        formatter: Callable[[BaseEvent], str] | None = None,
        console: Any | None = None,
        categories: set[str] | None = None,
    ) -> None:
        """Initialize the console handler."""
        from agent_actions.logging.core.events import EventLevel

        self.min_level = min_level or EventLevel.INFO
        self.show_timestamp = show_timestamp
        self.formatter = formatter
        self.categories = categories

        if RICH_AVAILABLE and Console is not None:
            self._console = console or Console(stderr=True)
            self._use_rich = True
        else:
            self._console = None
            self._use_rich = False

    def accepts(self, event: BaseEvent) -> bool:
        """Check if this event passes level and category filters."""
        from agent_actions.logging.core.events import EventLevel

        level_order = EventLevel.ordered()
        if level_order.index(event.level) < level_order.index(self.min_level):
            return False

        # WARN and ERROR always shown regardless of category — errors from
        # any module (llm, processing, prompt, etc.) must be visible.
        if event.level in (EventLevel.WARN, EventLevel.ERROR):
            return True

        if self.categories is not None and event.category not in self.categories:
            return False

        return True

    def handle(self, event: BaseEvent) -> None:
        """Output the event to the console."""
        if self.formatter:
            message = self.formatter(event)
        else:
            message = self._default_format(event)

        if self._use_rich and self._console:
            self._console.print(message, highlight=False)
        else:
            print(message, file=sys.stderr)

    def flush(self) -> None:
        """Flush console output."""
        sys.stderr.flush()

    def close(self) -> None:
        """Close the handler (no-op for console)."""

    def _default_format(self, event: BaseEvent) -> str:
        """Default event formatting."""
        from agent_actions.logging.core.events import EventLevel

        parts = []

        if self.show_timestamp:
            ts = event.meta.timestamp
            time_str = ts.strftime("%H:%M:%S")
            parts.append(f"[dim]{time_str}[/dim]" if self._use_rich else time_str)

        level_indicators = {
            EventLevel.DEBUG: ("[dim]DEBUG[/dim]", "DEBUG"),
            EventLevel.INFO: ("[blue]INFO[/blue]", "INFO"),
            EventLevel.WARN: ("[yellow]WARN[/yellow]", "WARN"),
            EventLevel.ERROR: ("[red]ERROR[/red]", "ERROR"),
        }
        rich_level, plain_level = level_indicators.get(event.level, ("[blue]INFO[/blue]", "INFO"))
        parts.append(rich_level if self._use_rich else plain_level)

        parts.append(event.message)

        separator = " | " if self.show_timestamp else " "
        return separator.join(parts)
