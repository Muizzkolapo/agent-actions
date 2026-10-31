"""Tests for orphan status entry handling (P1-2 Bug B).

Verifies that is_workflow_complete, is_workflow_done, has_any_failed,
and get_summary iterate execution_order (current YAML actions) rather
than action_status (which may contain stale orphan entries from removed
actions).
"""

import pytest

from agent_actions.workflow.managers.state import (
    ActionStateManager,
    ActionStatus,
)


def _make_state_manager(tmp_path, execution_order, extra_statuses=None):
    """Build a StateManager and inject orphan entries into action_status."""
    sm = ActionStateManager(
        status_file_path=tmp_path / "status.json",
        execution_order=execution_order,
    )
    if extra_statuses:
        for name, status in extra_statuses.items():
            sm.action_status[name] = {"status": status}
    return sm


class TestOrphanEntriesIgnored:
    """Orphan entries in action_status must not affect workflow-level queries."""

    @pytest.mark.parametrize(
        ("query", "orphans", "current", "expected"),
        [
            pytest.param(
                "is_workflow_complete",
                {"orphan_action": ActionStatus.FAILED},
                ActionStatus.COMPLETED,
                True,
                id="complete_ignores_orphan_failed",
            ),
            pytest.param(
                "is_workflow_done",
                {"orphan_action": ActionStatus.PENDING},
                ActionStatus.COMPLETED,
                True,
                id="done_ignores_orphan_pending",
            ),
            pytest.param(
                "is_workflow_done",
                None,
                ActionStatus.RUNNING,
                False,
                id="not_done_while_current_running",
            ),
            pytest.param(
                "has_any_failed",
                {"orphan_action": ActionStatus.FAILED},
                ActionStatus.COMPLETED,
                False,
                id="no_failure_from_orphan_failed",
            ),
        ],
    )
    def test_workflow_query_reads_only_current_actions(
        self, tmp_path, query, orphans, current, expected
    ):
        sm = _make_state_manager(tmp_path, execution_order=["action_a"], extra_statuses=orphans)
        sm.update_status("action_a", current)

        assert getattr(sm, query)() is expected

    def test_get_summary_excludes_orphans(self, tmp_path):
        sm = _make_state_manager(
            tmp_path,
            execution_order=["action_a", "action_b"],
            extra_statuses={"orphan_action": ActionStatus.FAILED},
        )
        sm.update_status("action_a", ActionStatus.COMPLETED)
        sm.update_status("action_b", ActionStatus.COMPLETED)

        summary = sm.get_summary()

        assert summary == {ActionStatus.COMPLETED: 2}
        assert ActionStatus.FAILED not in summary

    def test_get_summary_counts_only_current_actions(self, tmp_path):
        sm = _make_state_manager(
            tmp_path,
            execution_order=["action_a", "action_b"],
        )
        sm.update_status("action_a", ActionStatus.COMPLETED)
        # action_b stays PENDING

        summary = sm.get_summary()

        assert summary[ActionStatus.COMPLETED] == 1
        assert summary[ActionStatus.PENDING] == 1
        assert len(summary) == 2


class TestSummaryKeysAreReadable:
    """get_summary() is annotated dict[str, int] and its keys reach the terminal."""

    def test_an_enum_status_is_reported_by_name(self, tmp_path):
        sm = _make_state_manager(
            tmp_path,
            ["a", "b"],
            {"a": ActionStatus.BATCH_SUBMITTED, "b": ActionStatus.COMPLETED},
        )

        summary = sm.get_summary()
        # ActionStatus is a str enum, so equality passes while formatting does
        # not: f"{ActionStatus.BATCH_SUBMITTED}" is "ActionStatus.BATCH_SUBMITTED".
        rendered = ", ".join(f"{k}: {v}" for k, v in summary.items())
        assert "ActionStatus." not in rendered, f"the summary reaches the terminal as {rendered!r}"
        assert "batch_submitted: 1" in rendered
        assert "completed: 1" in rendered

    def test_a_string_status_is_left_alone(self, tmp_path):
        sm = _make_state_manager(tmp_path, ["a"], {"a": "completed"})

        assert sm.get_summary() == {"completed": 1}
