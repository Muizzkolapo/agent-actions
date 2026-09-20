"""A completion stamp left by a run that was capped from outside its config.

Such a run recorded the limit its config asked for, not the smaller one it
actually ran under, so the action reads as finished and is skipped for good.
The cap it ran under was written beside it under a key nothing reads.
"""

import json

import pytest

from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus


def manager(tmp_path, **details):
    path = tmp_path / ".agent_status.json"
    path.write_text(json.dumps({"act": {"status": "completed", **details}}, indent=2))
    return ActionStateManager(path, ["act"])


def written(tmp_path) -> dict:
    return json.loads((tmp_path / ".agent_status.json").read_text())["act"]


class TestAStampThatRecordedACap:
    def test_a_cap_below_the_configured_limit_is_a_truncation(self, tmp_path):
        state = manager(tmp_path, record_limit=8, max_records=2)

        assert state.adopt_truncation_marker("act") is True

    def test_a_cap_with_no_configured_limit_is_a_truncation(self, tmp_path):
        """No limit was asked for, so any cap cut the run short."""
        state = manager(tmp_path, record_limit=None, max_records=2)

        assert state.adopt_truncation_marker("act") is True

    def test_a_cap_equal_to_the_configured_limit_is_not(self, tmp_path):
        """The run stopped where its config said to stop."""
        state = manager(tmp_path, record_limit=2, max_records=2)

        assert state.adopt_truncation_marker("act") is False

    def test_a_null_cap_is_not(self, tmp_path):
        state = manager(tmp_path, record_limit=8, max_records=None)

        assert state.adopt_truncation_marker("act") is False

    def test_a_stamp_without_the_key_is_not(self, tmp_path):
        state = manager(tmp_path, record_limit=8)

        assert state.adopt_truncation_marker("act") is False


class TestTheMarkerIsRemovedAsItIsRead:
    @pytest.mark.parametrize("cap", [2, None])
    def test_the_key_does_not_survive_the_read(self, tmp_path, cap):
        state = manager(tmp_path, record_limit=8, max_records=cap)

        state.adopt_truncation_marker("act")

        assert "max_records" not in state.get_status_details("act")
        assert "max_records" not in written(tmp_path)

    def test_a_second_read_reports_nothing(self, tmp_path):
        """One-way: the stamp cannot invalidate the same action twice, so an
        action re-run once is not re-run again on every later run."""
        state = manager(tmp_path, record_limit=8, max_records=2)

        first = state.adopt_truncation_marker("act")
        second = state.adopt_truncation_marker("act")

        assert (first, second) == (True, False)

    def test_nothing_else_in_the_stamp_moves(self, tmp_path):
        state = manager(tmp_path, record_limit=8, max_records=2, config_hash="abc", file_limit=3)

        state.adopt_truncation_marker("act")

        assert written(tmp_path) == {
            "status": "completed",
            "record_limit": 8,
            "config_hash": "abc",
            "file_limit": 3,
        }

    def test_a_stamp_without_the_key_is_not_rewritten(self, tmp_path):
        state = manager(tmp_path, record_limit=8)
        before = (tmp_path / ".agent_status.json").read_text()

        state.adopt_truncation_marker("act")

        assert (tmp_path / ".agent_status.json").read_text() == before


class TestAnActionThatWasNeverCapped:
    def test_an_unknown_action_reports_nothing(self, tmp_path):
        state = manager(tmp_path, record_limit=8, max_records=2)

        assert state.adopt_truncation_marker("other") is False

    def test_a_pending_action_is_left_alone(self, tmp_path):
        """Only a completion stamp can serve a truncated run as a finished one."""
        path = tmp_path / ".agent_status.json"
        path.write_text(json.dumps({"act": {"status": "pending", "max_records": 2}}))
        state = ActionStateManager(path, ["act"])

        assert state.adopt_truncation_marker("act") is False
        assert state.get_status("act") == ActionStatus.PENDING
