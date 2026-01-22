"""
Console event handler for user-facing output.

Provides clean, dbt-style console output using Rich for formatting.
This handler shows high-level progress and errors to the user,
filtering out debug noise.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent, EventLevel

# Try to import Rich, fall back to plain print if not available
try:
    from rich.console import Console

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    Console = None  # type: ignore


class ConsoleEventHandler:
    """
    Handler that outputs events to the console.

    Provides dbt-style output with timestamps and status indicators.
    Uses Rich for colored output when available.

    Output format:
        10:30:45 | Starting workflow my_workflow (5 agents)
        10:30:46 | 1/5 OK extract_data in 12.34s
        10:30:47 | 2/5 SKIP transform (cached)
        10:31:00 | Completed in 15.00s | 4 OK | 1 SKIP | 0 ERROR

    Attributes:
        min_level: Minimum event level to display (default: INFO)
        show_timestamp: Whether to show timestamps (default: True)
        formatter: Optional custom formatter function
    """

    def __init__(
        self,
        min_level: EventLevel | None = None,
        show_timestamp: bool = True,
        formatter: Callable[[BaseEvent], str] | None = None,
        console: Any | None = None,
        categories: set[str] | None = None,
    ) -> None:
        """
        Initialize the console handler.

        Args:
            min_level: Minimum event level to display (default: INFO)
            show_timestamp: Whether to prefix output with timestamps
            formatter: Custom function to format events to strings
            console: Rich Console instance (creates new one if not provided)
            categories: Set of categories to display (None = all)
        """
        from agent_actions.logging.core.events import EventLevel

        self.min_level = min_level or EventLevel.INFO
        self.show_timestamp = show_timestamp
        self.formatter = formatter
        self.categories = categories

        # Initialize Rich console if available
        if RICH_AVAILABLE and Console is not None:
            self._console = console or Console(stderr=True)
            self._use_rich = True
        else:
            self._console = None
            self._use_rich = False

    def accepts(self, event: BaseEvent) -> bool:
        """
        Check if this event should be displayed.

        Filters by minimum level and optionally by category.

        Args:
            event: Event to check

        Returns:
            True if event should be displayed
        """
        from agent_actions.logging.core.events import EventLevel

        # Check level
        level_order = [EventLevel.DEBUG, EventLevel.INFO, EventLevel.WARN, EventLevel.ERROR]
        if level_order.index(event.level) < level_order.index(self.min_level):
            return False

        # Check category if filter is set
        if self.categories is not None and event.category not in self.categories:
            return False

        return True

    def handle(self, event: BaseEvent) -> None:
        """
        Output the event to the console.

        Args:
            event: Event to display
        """
        # Format the event
        if self.formatter:
            message = self.formatter(event)
        else:
            message = self._default_format(event)

        # Output
        if self._use_rich and self._console:
            self._console.print(message, highlight=False)
        else:
            print(message, file=sys.stderr)

    def flush(self) -> None:
        """Flush console output."""
        sys.stderr.flush()

    def _default_format(self, event: BaseEvent) -> str:
        """
        Default event formatting (dbt-style).

        Args:
            event: Event to format

        Returns:
            Formatted string for console output
        """
        from agent_actions.logging.core.events import EventLevel

        parts = []

        # Timestamp
        if self.show_timestamp:
            ts = event.meta.timestamp
            if isinstance(ts, datetime):
                time_str = ts.strftime("%H:%M:%S")
            else:
                time_str = datetime.now().strftime("%H:%M:%S")
            parts.append(f"[dim]{time_str}[/dim]" if self._use_rich else time_str)

        # Level indicator with color
        level_indicators = {
            EventLevel.DEBUG: ("[dim]DEBUG[/dim]", "DEBUG"),
            EventLevel.INFO: ("[blue]INFO[/blue]", "INFO"),
            EventLevel.WARN: ("[yellow]WARN[/yellow]", "WARN"),
            EventLevel.ERROR: ("[red]ERROR[/red]", "ERROR"),
        }
        rich_level, plain_level = level_indicators.get(event.level, ("[blue]INFO[/blue]", "INFO"))
        parts.append(rich_level if self._use_rich else plain_level)

        # Message
        parts.append(event.message)

        # Join with separator
        separator = " | " if self.show_timestamp else " "
        return separator.join(parts)


class QuietConsoleHandler(ConsoleEventHandler):
    """
    Minimal console handler that only shows errors and warnings.

    Use this for quiet/silent mode where only problems are reported.
    """

    def __init__(self, **kwargs: Any) -> None:
        from agent_actions.logging.core.events import EventLevel

        super().__init__(min_level=EventLevel.WARN, **kwargs)


class VerboseConsoleHandler(ConsoleEventHandler):
    """
    Verbose console handler that shows all events including debug.

    Use this for debugging and troubleshooting.
    """

    def __init__(self, **kwargs: Any) -> None:
        from agent_actions.logging.core.events import EventLevel

        super().__init__(min_level=EventLevel.DEBUG, **kwargs)
