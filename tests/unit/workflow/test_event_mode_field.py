"""Tests for mode field on action lifecycle events (ARCH-006)."""

from agent_actions.logging.events import (
    ActionCachedEvent,
    ActionCompleteEvent,
    ActionFailedEvent,
    ActionSkipEvent,
    ActionStartEvent,
)


class TestActionEventModeField:
    """Verify mode field is present and propagated on all action events."""

    def test_action_start_event_carries_mode(self):
        event = ActionStartEvent(action_name="extract", mode="online")
        assert event.mode == "online"
        assert event.data["mode"] == "online"

    def test_action_complete_event_carries_mode(self):
        event = ActionCompleteEvent(action_name="extract", mode="batch")
        assert event.mode == "batch"
        assert event.data["mode"] == "batch"

    def test_action_skip_event_carries_mode(self):
        event = ActionSkipEvent(action_name="extract", skip_reason="cached", mode="online")
        assert event.mode == "online"
        assert event.data["mode"] == "online"

    def test_action_failed_event_carries_mode(self):
        event = ActionFailedEvent(action_name="extract", error_message="boom", mode="batch")
        assert event.mode == "batch"
        assert event.data["mode"] == "batch"

    def test_action_cached_event_carries_mode(self):
        event = ActionCachedEvent(action_name="extract", mode="online")
        assert event.mode == "online"
        assert event.data["mode"] == "online"

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
