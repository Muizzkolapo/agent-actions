"""The console's own line format reads event text as text, not as markup.

A handler built with no formatter falls back to its own format. Rich read a bracketed
action at the start of a message as a style tag there too.
"""

import io

from rich.console import Console

from agent_actions.logging.core.events import EventLevel
from agent_actions.logging.core.handlers.bridge import LogEvent
from agent_actions.logging.core.handlers.console import ConsoleEventHandler


def _handler():
    stream = io.StringIO()
    console = Console(
        file=stream, width=200, force_terminal=False, color_system=None, highlight=False
    )
    return stream, ConsoleEventHandler(show_timestamp=False, console=console)


def _log(message: str) -> LogEvent:
    return LogEvent(
        level=EventLevel.WARN,
        category="processing",
        message=message,
        logger_name="agent_actions.processing.x",
    )


def test_a_leading_action_name_is_printed():
    stream, handler = _handler()

    handler.handle(_log("[fragile] Error executing UDF 'fragile': gamma breaks"))

    assert "[fragile] Error executing UDF 'fragile': gamma breaks" in stream.getvalue()


def test_a_closing_tag_that_matches_nothing_is_printed_as_written():
    stream, handler = _handler()

    handler.handle(_log("[fragile] gamma breaks on [/note] tag"))

    assert "gamma breaks on [/note] tag" in stream.getvalue()


def test_the_levels_own_colour_is_still_applied():
    """The message is escaped and the handler's own markup is not."""
    _, handler = _handler()

    line = handler._default_format(_log("[fragile] boom"))

    assert "[yellow]WARN[/yellow]" in line
