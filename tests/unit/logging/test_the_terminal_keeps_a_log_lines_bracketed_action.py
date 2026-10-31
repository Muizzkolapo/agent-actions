"""A log line that opens with `[action]` reaches the terminal with it.

Rich reads a bracketed word as a style tag, so a line written `[fragile] Error executing
UDF ...` printed without its action name — often the only place an LLM action's error
names it. A closing tag that matched no open one, which an error quoting record content
or a provider reply can hold, raised `MarkupError` and the line was replaced by a
traceback.
"""

import io

import pytest
from rich.console import Console

from agent_actions.logging.core.events import EventLevel
from agent_actions.logging.core.handlers.bridge import LogEvent
from agent_actions.logging.core.handlers.progress import ProgressRenderer
from agent_actions.logging.events import (
    ActionFailedEvent,
    ActionSkipEvent,
    BatchSubmittedEvent,
    WorkflowFailedEvent,
)
from agent_actions.logging.events.formatters import AgentActionsFormatter


def _terminal(use_color: bool = True):
    stream = io.StringIO()
    console = Console(
        file=stream, width=200, force_terminal=False, color_system=None, highlight=False
    )
    renderer = ProgressRenderer(
        show_timestamp=False,
        formatter=AgentActionsFormatter(show_timestamp=False, use_color=use_color).format,
        console=console,
    )
    return stream, renderer


def _log(message: str) -> LogEvent:
    return LogEvent(
        level=EventLevel.WARN,
        category="processing",
        message=message,
        logger_name="agent_actions.processing.x",
    )


class TestABracketedActionNameSurvives:
    def test_a_leading_action_name_is_printed(self):
        stream, renderer = _terminal()

        renderer.handle(_log("[fragile] Error executing UDF 'fragile': gamma breaks"))

        assert "[fragile] Error executing UDF 'fragile': gamma breaks" in stream.getvalue()

    def test_a_name_that_is_also_a_style_name_is_printed(self):
        stream, renderer = _terminal()

        renderer.handle(_log("[bold] Record 2 exhausted: exhausted_after_2_attempts"))

        assert "[bold] Record 2 exhausted" in stream.getvalue()


class TestAClosingTagInAMessageDoesNotReplaceTheLine:
    def test_a_closing_tag_that_matches_nothing_is_printed_as_written(self):
        stream, renderer = _terminal()

        renderer.handle(_log("[fragile] gamma breaks on [/note] tag (record a97148de)"))

        assert "gamma breaks on [/note] tag (record a97148de)" in stream.getvalue()

    def test_the_handler_raises_nothing_for_it(self):
        _, renderer = _terminal()

        renderer.handle(_log("a reply holding [/note] and [/]"))


class TestWhatItMustNotChange:
    def test_a_plain_stream_shows_no_added_backslashes(self):
        """Without Rich the text is written as it is, so an escape would show."""
        _, renderer = _terminal(use_color=False)
        renderer._use_rich = False
        written = []
        renderer._write = written.append  # type: ignore[method-assign]

        renderer.handle(_log("[fragile] boom"))

        assert written == ["[fragile] boom"]

    def test_the_formatter_still_colours_its_own_status_words(self):
        """The message is escaped, the formatter's own tags are not."""
        formatter = AgentActionsFormatter(show_timestamp=False, use_color=True)

        assert formatter._status("OK") == "[green]OK[/green]"


TRICKY = "gamma breaks on [/note] and [fragile] tags"


def _failed():
    return ActionFailedEvent(
        action_name="fragile",
        total_actions=1,
        error_message=TRICKY,
        suggestion="retry [/note] later",
    )


def _skipped():
    return ActionSkipEvent(action_name="fragile", total_actions=1, skip_reason=TRICKY)


def _workflow_failed():
    return WorkflowFailedEvent(workflow_name="wf", error_message=TRICKY)


def _batch():
    return BatchSubmittedEvent(batch_id="b-1", request_count=2, provider=TRICKY)


class TestTheFormatterEscapesWhatEventsCarry:
    """Each method that puts event data in a line, read as the terminal reads it."""

    @pytest.mark.parametrize(
        "make, expected",
        [
            (_failed, "gamma breaks on [/note] and [fragile] tags"),
            (_failed, "retry [/note] later"),
            (_skipped, "gamma breaks on [/note] and [fragile] tags"),
            (_workflow_failed, "gamma breaks on [/note] and [fragile] tags"),
            (_batch, "gamma breaks on [/note] and [fragile] tags"),
        ],
    )
    def test_the_text_survives_being_read_as_markup(self, make, expected):
        from rich.text import Text

        line = AgentActionsFormatter(show_timestamp=False, use_color=True).format(make())

        assert expected in Text.from_markup(line).plain

    def test_without_colour_the_text_is_written_as_it_is(self):
        line = AgentActionsFormatter(show_timestamp=False, use_color=False).format(_failed())

        assert "gamma breaks on [/note] and [fragile] tags" in line
        assert "\\[" not in line
