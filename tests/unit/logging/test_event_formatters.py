"""Tests for AgentActionsFormatter event formatting."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from agent_actions.logging.core.events import BaseEvent, EventMeta
from agent_actions.logging.events.formatters import AgentActionsFormatter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: str,
    data: dict | None = None,
    message: str = "",
    timestamp: datetime | None = None,
) -> BaseEvent:
    """Build a BaseEvent-like mock with the given event_type and data.

    We use a plain BaseEvent (not a MagicMock) because event.data must be a
    real dict so that .get() works as expected in the formatters.
    """
    ts = timestamp or datetime(2025, 6, 15, 10, 30, 45, tzinfo=UTC)
    event = BaseEvent()
    event.meta = EventMeta(timestamp=ts)
    event.data = data or {}
    event.message = message
    # Override event_type property via the class name trick: we subclass on the
    # fly so that __class__.__name__ returns the desired event_type string.
    event.__class__ = type(event_type, (BaseEvent,), {})
    return event


# ---------------------------------------------------------------------------
# Construction / init
# ---------------------------------------------------------------------------


class TestFormatterInit:
    """Tests for AgentActionsFormatter initialization."""

    def test_default_init(self):
        fmt = AgentActionsFormatter()
        assert fmt.show_timestamp is True

    def test_no_timestamp(self):
        fmt = AgentActionsFormatter(show_timestamp=False)
        assert fmt.show_timestamp is False

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_use_color_enabled_when_rich_available(self):
        fmt = AgentActionsFormatter(use_color=True)
        assert fmt.use_color is True

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", False)
    def test_use_color_disabled_when_rich_unavailable(self):
        fmt = AgentActionsFormatter(use_color=True)
        assert fmt.use_color is False

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_use_color_disabled_explicitly(self):
        fmt = AgentActionsFormatter(use_color=False)
        assert fmt.use_color is False


# ---------------------------------------------------------------------------
# Timestamp formatting
# ---------------------------------------------------------------------------


class TestTimestamp:
    """Tests for _timestamp helper."""

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_timestamp_with_color(self):
        fmt = AgentActionsFormatter(show_timestamp=True, use_color=True)
        event = _make_event("X", timestamp=datetime(2025, 1, 2, 13, 45, 59, tzinfo=UTC))
        ts = fmt._timestamp(event)
        assert "[dim]13:45:59[/dim] | " == ts

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", False)
    def test_timestamp_without_color(self):
        fmt = AgentActionsFormatter(show_timestamp=True, use_color=True)
        event = _make_event("X", timestamp=datetime(2025, 1, 2, 13, 45, 59, tzinfo=UTC))
        ts = fmt._timestamp(event)
        assert "13:45:59 | " == ts

    def test_timestamp_hidden(self):
        fmt = AgentActionsFormatter(show_timestamp=False)
        event = _make_event("X")
        assert fmt._timestamp(event) == ""


# ---------------------------------------------------------------------------
# Status formatting
# ---------------------------------------------------------------------------


class TestStatus:
    """Tests for _status helper."""

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_status_colored(self):
        fmt = AgentActionsFormatter(use_color=True)
        assert fmt._status("OK") == "[green]OK[/green]"
        assert fmt._status("ERROR") == "[red]ERROR[/red]"
        assert fmt._status("SKIP") == "[yellow]SKIP[/yellow]"
        assert fmt._status("CACHED") == "[cyan]CACHED[/cyan]"
        assert fmt._status("START") == "[blue]START[/blue]"
        assert fmt._status("WARN") == "[yellow]WARN[/yellow]"

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_status_unknown_returns_plain(self):
        fmt = AgentActionsFormatter(use_color=True)
        assert fmt._status("MYSTERY") == "MYSTERY"

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", False)
    def test_status_no_color(self):
        fmt = AgentActionsFormatter(use_color=True)
        assert fmt._status("OK") == "OK"


# ---------------------------------------------------------------------------
# Dispatch table — all event types
# ---------------------------------------------------------------------------


class TestWorkflowStartEvent:
    """Tests for _format_workflow_start."""

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_sequential_mode_with_color(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "WorkflowStartEvent",
            data={
                "workflow_name": "my_wf",
                "action_count": 3,
                "execution_mode": "sequential",
            },
        )
        result = fmt.format(event)
        assert "my_wf" in result
        assert "3 actions" in result
        assert "[bold]my_wf[/bold]" in result
        # Sequential mode should NOT append mode string
        assert "[sequential]" not in result

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_parallel_mode_appended(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "WorkflowStartEvent",
            data={
                "workflow_name": "wf",
                "action_count": 5,
                "execution_mode": "parallel",
            },
        )
        result = fmt.format(event)
        assert "[parallel]" in result

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", False)
    def test_no_color(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "WorkflowStartEvent",
            data={"workflow_name": "wf", "action_count": 2, "execution_mode": "sequential"},
        )
        result = fmt.format(event)
        assert "[bold]" not in result
        assert "wf" in result

    def test_missing_fields_use_defaults(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=False)
        event = _make_event("WorkflowStartEvent", data={})
        result = fmt.format(event)
        assert "(0 actions)" in result


class TestWorkflowCompleteEvent:
    """Tests for _format_workflow_complete."""

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_all_counters(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "WorkflowCompleteEvent",
            data={
                "elapsed_time": 12.5,
                "actions_completed": 3,
                "actions_skipped": 1,
                "actions_failed": 2,
            },
        )
        result = fmt.format(event)
        assert "12.50s" in result
        assert "3 [green]OK[/green]" in result
        assert "1 [yellow]SKIP[/yellow]" in result
        assert "2 [red]ERROR[/red]" in result

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_zero_counters_no_color_on_status(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "WorkflowCompleteEvent",
            data={
                "elapsed_time": 0.0,
                "actions_completed": 0,
                "actions_skipped": 0,
                "actions_failed": 0,
            },
        )
        result = fmt.format(event)
        # When count is 0, status is plain text (no color markup)
        assert "0 OK" in result
        assert "0 SKIP" in result
        assert "0 ERROR" in result
        assert "[green]" not in result


class TestWorkflowFailedEvent:
    """Tests for _format_workflow_failed."""

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_format(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "WorkflowFailedEvent",
            data={"workflow_name": "wf", "error_message": "boom"},
        )
        result = fmt.format(event)
        assert "[red]ERROR[/red]" in result
        assert "wf" in result
        assert "boom" in result


class TestActionStartEvent:
    """Tests for _format_action_start."""

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_format(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "ActionStartEvent",
            data={"action_index": 0, "total_actions": 3, "action_name": "node_a"},
        )
        result = fmt.format(event)
        assert "1/3" in result
        assert "[blue]START[/blue]" in result
        assert "node_a" in result


class TestActionCompleteEvent:
    """Tests for _format_action_complete."""

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_with_tokens(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "ActionCompleteEvent",
            data={
                "action_index": 1,
                "total_actions": 5,
                "action_name": "gen",
                "execution_time": 2.34,
                "tokens": {"total_tokens": 500},
            },
        )
        result = fmt.format(event)
        assert "2/5" in result
        assert "[green]OK[/green]" in result
        assert "2.34s" in result
        assert "(500 tokens)" in result

    def test_no_tokens(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=False)
        event = _make_event(
            "ActionCompleteEvent",
            data={
                "action_index": 0,
                "total_actions": 1,
                "action_name": "gen",
                "execution_time": 1.0,
                "tokens": {"total_tokens": 0},
            },
        )
        result = fmt.format(event)
        assert "tokens" not in result

    def test_missing_tokens_dict(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=False)
        event = _make_event(
            "ActionCompleteEvent",
            data={
                "action_index": 0,
                "total_actions": 1,
                "action_name": "gen",
                "execution_time": 1.0,
            },
        )
        result = fmt.format(event)
        assert "tokens" not in result


class TestActionSkipEvent:
    """Tests for _format_action_skip."""

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_with_reason(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "ActionSkipEvent",
            data={
                "action_index": 2,
                "total_actions": 4,
                "action_name": "node_x",
                "skip_reason": "cached",
            },
        )
        result = fmt.format(event)
        assert "3/4" in result
        assert "[yellow]SKIP[/yellow]" in result
        assert "(cached)" in result

    def test_without_reason(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=False)
        event = _make_event(
            "ActionSkipEvent",
            data={
                "action_index": 0,
                "total_actions": 1,
                "action_name": "n",
                "skip_reason": "",
            },
        )
        result = fmt.format(event)
        # No parenthetical when reason is empty
        assert "(" not in result


class TestActionCachedEvent:
    """Tests for _format_action_cached."""

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_format(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "ActionCachedEvent",
            data={"action_index": 0, "total_actions": 2, "action_name": "node_c"},
        )
        result = fmt.format(event)
        assert "1/2" in result
        assert "[cyan]CACHED[/cyan]" in result
        assert "node_c" in result


class TestActionFailedEvent:
    """Tests for _format_action_failed."""

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_with_suggestion(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "ActionFailedEvent",
            data={
                "action_index": 0,
                "total_actions": 1,
                "action_name": "bad",
                "error_message": "timeout",
                "suggestion": "increase limit",
            },
        )
        result = fmt.format(event)
        assert "[red]ERROR[/red]" in result
        assert "bad: timeout" in result
        assert "[dim]Suggestion: increase limit[/dim]" in result

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", False)
    def test_suggestion_no_color(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "ActionFailedEvent",
            data={
                "action_index": 0,
                "total_actions": 1,
                "action_name": "bad",
                "error_message": "err",
                "suggestion": "fix it",
            },
        )
        result = fmt.format(event)
        assert "Suggestion: fix it" in result
        assert "[dim]" not in result

    def test_without_suggestion(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=False)
        event = _make_event(
            "ActionFailedEvent",
            data={
                "action_index": 0,
                "total_actions": 1,
                "action_name": "bad",
                "error_message": "err",
                "suggestion": "",
            },
        )
        result = fmt.format(event)
        assert "Suggestion" not in result


class TestBatchSubmittedEvent:
    """Tests for _format_batch_submitted."""

    def test_truncates_batch_id(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=False)
        long_id = "abcdef1234567890"
        event = _make_event(
            "BatchSubmittedEvent",
            data={
                "batch_id": long_id,
                "request_count": 10,
                "provider": "openai",
            },
        )
        result = fmt.format(event)
        # ID truncated to first 8 chars
        assert "abcdef12" in result
        assert long_id not in result
        assert "10 requests to openai" in result


class TestBatchCompleteEvent:
    """Tests for _format_batch_complete."""

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_no_failures(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "BatchCompleteEvent",
            data={
                "batch_id": "12345678",
                "elapsed_time": 5.5,
                "failed": 0,
            },
        )
        result = fmt.format(event)
        assert "[green]OK[/green]" in result
        assert "5.50s" in result

    @patch("agent_actions.logging.events.formatters.RICH_AVAILABLE", True)
    def test_with_failures(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=True)
        event = _make_event(
            "BatchCompleteEvent",
            data={
                "batch_id": "12345678",
                "elapsed_time": 3.0,
                "failed": 2,
            },
        )
        result = fmt.format(event)
        assert "[yellow]WARN[/yellow]" in result
        assert "(2 failed)" in result


# ---------------------------------------------------------------------------
# Default / unknown event types
# ---------------------------------------------------------------------------


class TestDefaultFormatting:
    """Tests for unknown event types falling through to _format_default."""

    def test_unknown_event_type(self):
        fmt = AgentActionsFormatter(show_timestamp=False, use_color=False)
        event = _make_event("SomeFutureEvent", message="hello world")
        result = fmt.format(event)
        assert result == "hello world"

    def test_unknown_event_type_with_timestamp(self):
        fmt = AgentActionsFormatter(show_timestamp=True, use_color=False)
        event = _make_event(
            "SomeFutureEvent",
            message="msg",
            timestamp=datetime(2025, 3, 1, 8, 0, 0, tzinfo=UTC),
        )
        result = fmt.format(event)
        assert result == "08:00:00 | msg"


# ---------------------------------------------------------------------------
# Dispatch table completeness
# ---------------------------------------------------------------------------


class TestDispatchCompleteness:
    """Verify all dispatch entries resolve to real methods."""

    def test_all_dispatch_methods_exist(self):
        fmt = AgentActionsFormatter()
        for event_type, method_name in fmt._DISPATCH.items():
            assert hasattr(fmt, method_name), (
                f"Dispatch entry '{event_type}' -> '{method_name}' does not exist"
            )
            assert callable(getattr(fmt, method_name))

    def test_dispatch_table_covers_expected_events(self):
        expected = {
            "WorkflowStartEvent",
            "WorkflowCompleteEvent",
            "WorkflowFailedEvent",
            "ActionStartEvent",
            "ActionCompleteEvent",
            "ActionSkipEvent",
            "ActionFailedEvent",
            "ActionCachedEvent",
            "BatchSubmittedEvent",
            "BatchCompleteEvent",
        }
        assert set(AgentActionsFormatter._DISPATCH.keys()) == expected
