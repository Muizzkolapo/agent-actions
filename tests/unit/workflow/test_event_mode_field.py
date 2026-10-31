"""Tests for mode field on action lifecycle events (ARCH-006)."""

import pytest

from agent_actions.logging.events import (
    ActionCachedEvent,
    ActionCompleteEvent,
    ActionFailedEvent,
    ActionSkipEvent,
    ActionStartEvent,
)


class TestActionEventModeField:
    """Verify mode field is present and propagated on all action events."""

    @pytest.mark.parametrize(
        ("event_cls", "extra", "mode"),
        [
            pytest.param(ActionStartEvent, {}, "online", id="start"),
            pytest.param(ActionCompleteEvent, {}, "batch", id="complete"),
            pytest.param(ActionSkipEvent, {"skip_reason": "cached"}, "online", id="skip"),
            pytest.param(ActionFailedEvent, {"error_message": "boom"}, "batch", id="failed"),
            pytest.param(ActionCachedEvent, {}, "online", id="cached"),
        ],
    )
    def test_action_event_carries_mode(self, event_cls, extra, mode):
        event = event_cls(action_name="extract", mode=mode, **extra)
        assert event.mode == mode
        assert event.data["mode"] == mode

    def test_mode_defaults_to_empty_string(self):
        """When mode is not provided, it defaults to empty string."""
        event = ActionStartEvent(action_name="extract")
        assert event.mode == ""
        assert event.data["mode"] == ""

    def test_mode_backward_compatible(self):
        """Existing code that doesn't pass mode should still work."""
        event = ActionCompleteEvent(
            action_name="extract",
            action_index=0,
            total_actions=3,
            execution_time=1.5,
            output_path="/out",
            tokens={"total_tokens": 100},
        )
        assert event.mode == ""
        assert event.data["action_name"] == "extract"
        assert event.data["tokens"] == {"total_tokens": 100}
