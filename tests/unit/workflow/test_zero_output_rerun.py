"""Tests for zero-output infinite rerun fix (P1-2 Bug A).

Verifies that _check_prior_output recognizes node-level terminal
dispositions (FILTERED, PASSTHROUGH, SUCCESS, UNPROCESSED) as
intentional no-output and does NOT reset the action to PENDING.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.storage.backend import (
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SKIPPED,
    DISPOSITION_SUCCESS,
    DISPOSITION_UNPROCESSED,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.workflow.executor import ActionExecutor
from agent_actions.workflow.managers.state import ActionStatus


def _make_executor():
    """Build a minimal ActionExecutor with mocked deps."""
    deps = MagicMock()
    executor = object.__new__(ActionExecutor)
    executor.deps = deps
    return executor


class TestCheckPriorOutputIntentionalNoOutput:
    """Node-level terminal dispositions prevent rerun when no target files."""

    @pytest.mark.parametrize(
        "disposition",
        [
            DISPOSITION_FILTERED,
            DISPOSITION_PASSTHROUGH,
            DISPOSITION_SUCCESS,
            DISPOSITION_UNPROCESSED,
        ],
        ids=["filtered", "passthrough", "success", "unprocessed"],
    )
    def test_node_level_disposition_skips_rerun(self, disposition):
        executor = _make_executor()
        backend = MagicMock()
        backend.list_target_files.return_value = []

        def has_disp(action, disp, record_id=None):
            if disp in (DISPOSITION_FAILED, DISPOSITION_SKIPPED):
                return False
            return disp == disposition and record_id == NODE_LEVEL_RECORD_ID

        backend.has_disposition.side_effect = has_disp

        has_output, result = executor._check_prior_output(backend, "my_action")

        assert has_output is True
        assert result is not None
        assert result.status == ActionStatus.COMPLETED
        # Must NOT reset to PENDING
        executor.deps.state_manager.update_status.assert_not_called()

    def test_no_disposition_no_files_resets_to_pending(self):
        executor = _make_executor()
        backend = MagicMock()
        backend.list_target_files.return_value = []
        backend.has_disposition.return_value = False

        has_output, result = executor._check_prior_output(backend, "my_action")

        assert has_output is False
        assert result is None
        executor.deps.state_manager.update_status.assert_called_once_with(
            "my_action", ActionStatus.PENDING
        )

    def test_target_files_exist_returns_completed(self):
        executor = _make_executor()
        backend = MagicMock()
        backend.list_target_files.return_value = ["output.json"]
        # No FAILED/SKIPPED disposition
        backend.has_disposition.return_value = False

        has_output, result = executor._check_prior_output(backend, "my_action")

        assert has_output is True
        assert result.status == ActionStatus.COMPLETED

    def test_failed_disposition_triggers_rerun(self):
        executor = _make_executor()
        backend = MagicMock()

        def has_disp(action, disp, record_id=None):
            return disp == DISPOSITION_FAILED and record_id == NODE_LEVEL_RECORD_ID

        backend.has_disposition.side_effect = has_disp

        has_output, result = executor._check_prior_output(backend, "my_action")

        assert has_output is False
        assert result is None
        backend.clear_disposition.assert_called_once_with(
            "my_action", DISPOSITION_FAILED, record_id=NODE_LEVEL_RECORD_ID
        )
        executor.deps.state_manager.update_status.assert_called_once_with(
            "my_action", ActionStatus.PENDING
        )

    def test_skipped_disposition_triggers_rerun(self):
        executor = _make_executor()
        backend = MagicMock()

        def has_disp(action, disp, record_id=None):
            return disp == DISPOSITION_SKIPPED and record_id == NODE_LEVEL_RECORD_ID

        backend.has_disposition.side_effect = has_disp

        has_output, result = executor._check_prior_output(backend, "my_action")

        assert has_output is False
        assert result is None
        backend.clear_disposition.assert_called_once_with(
            "my_action", DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID
        )


class TestCheckPriorOutputDoesNotRunStatsQuery:
    """The cached-completion branch is THIS execution didn't produce records.

    Regression for the spec 554 review finding: the previous implementation
    called _count_output_records eagerly while building the `completed`
    tuple — even on the cold-start path that returned (False, None).  For a
    50-action workflow with all-pending status, that was ~50 wasted
    whole-DB stats queries per scheduling pass.
    """

    def test_cold_start_does_not_query_storage_stats(self):
        # No prior output, no dispositions — the executor will reset to
        # PENDING and return (False, None).  It must NOT call
        # get_storage_stats on the way (the prior eager-builder did).
        executor = _make_executor()
        backend = MagicMock()
        backend.list_target_files.return_value = []
        backend.has_disposition.return_value = False

        has_output, result = executor._check_prior_output(backend, "my_action")

        assert has_output is False
        assert result is None
        backend.get_storage_stats.assert_not_called()

    def test_cached_completion_ships_record_count_zero(self):
        # Cached completion (target files exist) — record_count is 0 because
        # this execution did not run the action.  The pre/post snapshot in
        # _execute_action_run is what produces the per-execution count.
        executor = _make_executor()
        backend = MagicMock()
        backend.list_target_files.return_value = ["output.json"]
        backend.has_disposition.return_value = False

        has_output, result = executor._check_prior_output(backend, "my_action")

        assert has_output is True
        assert result is not None
        assert result.metrics.record_count == 0, (
            f"cached-completion path must ship record_count=0 (this execution "
            f"did not run the action), got {result.metrics.record_count}"
        )
        backend.get_storage_stats.assert_not_called()

    def test_node_level_filtered_disposition_ships_record_count_zero(self):
        # Intentional no-output path (guard-filtered all, etc.) — also 0.
        executor = _make_executor()
        backend = MagicMock()
        backend.list_target_files.return_value = []

        def has_disp(action, disp, record_id=None):
            if disp in (DISPOSITION_FAILED, DISPOSITION_SKIPPED):
                return False
            return disp == DISPOSITION_FILTERED and record_id == NODE_LEVEL_RECORD_ID

        backend.has_disposition.side_effect = has_disp

        has_output, result = executor._check_prior_output(backend, "my_action")

        assert has_output is True
        assert result.metrics.record_count == 0
        backend.get_storage_stats.assert_not_called()
