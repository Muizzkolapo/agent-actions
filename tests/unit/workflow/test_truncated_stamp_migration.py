"""A completion stamp left by a run that was capped from outside its config.

Such a run recorded the limit its config asked for, not the smaller one it
actually ran under, so the action reads as finished and is skipped for good.
The cap it ran under was written beside it under a key nothing reads.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
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


class TestACapThatNeverCappedAnything:
    """A count, on the terms the limit resolver already sets."""

    @pytest.mark.parametrize("cap", [True, False, 0, -1, "2"])
    def test_it_reports_nothing(self, tmp_path, cap):
        state = manager(tmp_path, record_limit=8, max_records=cap)

        assert state.adopt_truncation_marker("act") is False

    @pytest.mark.parametrize("cap", [True, False, 0, -1, "2"])
    def test_the_key_still_goes(self, tmp_path, cap):
        state = manager(tmp_path, record_limit=8, max_records=cap)

        state.adopt_truncation_marker("act")

        assert "max_records" not in written(tmp_path)


class TestTheMarkerOutlivesTheReadThatReportsIt:
    """Removing it is the reopening write's job. Saving the removal here puts
    the stamp through a moment where it is completed, carries the configured
    limit, and no longer records the cap — the shape this exists to remove."""

    def test_the_file_still_holds_it_until_the_action_is_reopened(self, tmp_path):
        state = manager(tmp_path, record_limit=8, max_records=2)

        assert state.adopt_truncation_marker("act") is True
        assert "max_records" in written(tmp_path)

    def test_a_crash_before_the_reopen_leaves_it_readable(self, tmp_path):
        """What a later run sees if the process dies in between."""
        manager(tmp_path, record_limit=8, max_records=2).adopt_truncation_marker("act")

        reloaded = ActionStateManager(tmp_path / ".agent_status.json", ["act"])

        assert reloaded.adopt_truncation_marker("act") is True

    def test_a_failed_write_leaves_it_readable(self, tmp_path):
        """The repo already models this: a save can raise, and every other
        invalidation reason survives it by being re-derived next run."""
        state = manager(tmp_path, record_limit=8, max_records=2)
        state.adopt_truncation_marker("act")
        with (
            patch.object(state, "_save_status", side_effect=OSError("disk full")),
            pytest.raises(OSError),
        ):
            state.update_status("act", ActionStatus.PENDING)

        reloaded = ActionStateManager(tmp_path / ".agent_status.json", ["act"])
        assert reloaded.adopt_truncation_marker("act") is True

    def test_the_reopening_write_carries_the_removal(self, tmp_path):
        state = manager(tmp_path, record_limit=8, max_records=2)
        state.adopt_truncation_marker("act")

        state.update_status("act", ActionStatus.PENDING)

        assert "max_records" not in written(tmp_path)

    def test_a_second_read_after_that_reports_nothing(self, tmp_path):
        """One-way: an action reopened once is not reopened again on every
        later run."""
        state = manager(tmp_path, record_limit=8, max_records=2)
        first = state.adopt_truncation_marker("act")
        state.update_status("act", ActionStatus.PENDING)

        reloaded = ActionStateManager(tmp_path / ".agent_status.json", ["act"])

        assert (first, reloaded.adopt_truncation_marker("act")) == (True, False)

    def test_nothing_else_in_the_stamp_moves(self, tmp_path):
        state = manager(tmp_path, record_limit=8, max_records=2, config_hash="abc", file_limit=3)
        state.adopt_truncation_marker("act")

        state.update_status("act", ActionStatus.PENDING)

        assert written(tmp_path) == {
            "status": "pending",
            "record_limit": 8,
            "config_hash": "abc",
            "file_limit": 3,
        }

    def test_a_stamp_without_the_key_is_not_rewritten(self, tmp_path):
        state = manager(tmp_path, record_limit=8)
        before = (tmp_path / ".agent_status.json").read_text()

        state.adopt_truncation_marker("act")

        assert (tmp_path / ".agent_status.json").read_text() == before

    def test_a_marker_that_reports_nothing_is_cleared_at_once(self, tmp_path):
        """Nothing is at stake in it, so it does not need a later write."""
        state = manager(tmp_path, record_limit=8, max_records=None)

        state.adopt_truncation_marker("act")

        assert "max_records" not in written(tmp_path)


class TestTheReopenIsWhatMakesTheRemovalDurable:
    """The claim the deferred write rests on. Driven through the real state
    manager: a mocked one answers about the call, not about the file."""

    def executor(self, state):
        deps = MagicMock(spec=ExecutorDependencies)
        deps.state_manager = state
        deps.action_runner = MagicMock()
        deps.action_runner.retried_records = frozenset()
        deps.action_runner.storage_backend = MagicMock()
        return ActionExecutor(deps)

    def test_reopening_clears_the_marker_from_the_file(self, tmp_path):
        state = manager(tmp_path, record_limit=8, max_records=2)

        result = self.executor(state)._maybe_invalidate_completed_status(
            "act", {"record_limit": 8}, ActionStatus.COMPLETED
        )

        assert result == ActionStatus.PENDING
        assert "max_records" not in written(tmp_path)
        assert written(tmp_path)["status"] == "pending"

    def test_the_stale_rows_go_with_it(self, tmp_path):
        """The action re-runs in full, so the rows it wrote while cut short
        must not read as already done."""
        state = manager(tmp_path, record_limit=8, max_records=2)
        executor = self.executor(state)

        executor._maybe_invalidate_completed_status(
            "act", {"record_limit": 8}, ActionStatus.COMPLETED
        )

        executor.deps.action_runner.storage_backend.clear_disposition.assert_called_once_with("act")


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
        # Nothing is at stake in a marker on an action that will run anyway.
        assert "max_records" not in written(tmp_path)
