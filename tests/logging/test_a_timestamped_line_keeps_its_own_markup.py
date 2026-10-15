"""With timestamps on, as the run always has them, the line's own colour is not escaped.

The formatter puts a `[dim]` timestamp in front of the text it escapes. Escaping the whole
line, rather than the event's text, would print that tag as characters.
"""

import io

import pytest

from agent_actions.logging.core.events import EventLevel
from agent_actions.logging.core.handlers.bridge import LogEvent
from agent_actions.logging.core.handlers.progress import ProgressRenderer
from agent_actions.logging.events import BatchSubmittedEvent
from agent_actions.logging.events.formatters import AgentActionsFormatter

rich_console = pytest.importorskip("rich.console")


def _printed(event) -> str:
    stream = io.StringIO()
    console = rich_console.Console(
        file=stream, width=200, force_terminal=False, color_system=None, highlight=False
    )
    renderer = ProgressRenderer(
        show_timestamp=True,
        formatter=AgentActionsFormatter(show_timestamp=True, use_color=True).format,
        console=console,
    )
    renderer.handle(event)
    return stream.getvalue()


def test_a_log_line_prints_its_text_and_no_literal_timestamp_tag():
    event = LogEvent(
        level=EventLevel.WARN,
        category="processing",
        message="[fragile] boom [/note]",
        logger_name="agent_actions.processing.x",
    )

    out = _printed(event)

    assert "[fragile] boom [/note]" in out
    assert "[dim]" not in out
    assert "[/dim]" not in out


def test_a_formatted_event_line_prints_its_text_and_no_literal_timestamp_tag():
    out = _printed(BatchSubmittedEvent(batch_id="b-1", request_count=2, provider="[/x]"))

    assert "to [/x]" in out
    assert "[dim]" not in out
