"""Regression tests for spec 557 — clear stale NODE_LEVEL disposition when an
action begins executing.

Cross-run scenario:

    Round 1: upstream is unhealthy, ``_handle_dependency_skip`` writes
             SKIPPED@NODE_LEVEL for action A.
    Round 2: upstream is healthy, action A actually runs and writes
             per-record output. The prior-round SKIPPED@NODE_LEVEL row
             has no in-round writer to overwrite it (``set_disposition``
             only DELETEs rows for the same ``(action_name, record_id)``
             it is about to INSERT), so it survives until
             ``_resolve_completion_status`` sees a "SKIPPED but output
             exists" contradiction and heals it with a scary warning.

The fix moves the invariant "NODE_LEVEL rows reflect the current round
only" into ``_execute_action_run`` — the exact moment the executor
commits to running this round. The old read-time heal at
``_resolve_completion_status`` becomes unreachable and is deleted.
"""

import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.storage.backend import (
    DISPOSITION_SKIPPED,
    DISPOSITION_SUCCESS,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.executor import (
    ActionExecutor,
    ActionRunParams,
    ExecutorDependencies,
)
from agent_actions.workflow.managers.state import ActionStatus


def _make_executor_with_real_backend(tmp_path: Path) -> tuple[ActionExecutor, SQLiteBackend]:
    """Build an ActionExecutor wired to a real SQLite backend.

    A real backend is used so disposition semantics (DELETE-then-INSERT in
    ``set_disposition``, keyed clear, etc.) match production — mocks would
    let the test pass without proving anything about the actual invariant.
    """
    backend = SQLiteBackend(str(tmp_path / "test.db"), "wf")
    backend.initialize()

    state_manager = MagicMock()
    state_manager.is_skipped.return_value = False
    state_manager.is_failed.return_value = False
    state_manager.execution_order = ["action_a"]

    action_runner = MagicMock()
    action_runner.storage_backend = backend
    action_runner.workflow_name = "wf"
    action_runner.get_action_folder.return_value = str(tmp_path)
    action_runner.execution_order = ["action_a"]
    action_runner.run_action.return_value = str(tmp_path / "output")

    batch_manager = MagicMock()
    batch_manager.check_batch_submission.return_value = None

    output_manager = MagicMock()
    output_manager.resolve_correlated_input.return_value = None

    deps = ExecutorDependencies(
        action_runner=action_runner,
        state_manager=state_manager,
        skip_evaluator=MagicMock(),
        batch_manager=batch_manager,
        output_manager=output_manager,
    )
    return ActionExecutor(deps=deps), backend


def _params(action_name: str = "action_a") -> ActionRunParams:
    return ActionRunParams(
        action_name=action_name,
        action_idx=0,
        action_config={"model_vendor": "openai", "model_name": "gpt-4"},
        is_last_action=False,
        start_time=datetime.now(),
    )


class TestStaleNodeDispositionClearedOnExecute:
    def test_prior_run_skipped_then_current_run_executes_clears_node_disposition(self, tmp_path):
        """Two-round scenario: prior run wrote SKIPPED@NODE_LEVEL; current run
        executes the action. The stale SKIPPED row is gone once
        ``_execute_action_run`` returns."""
        executor, backend = _make_executor_with_real_backend(tmp_path)

        backend.set_disposition(
            action_name="action_a",
            record_id=NODE_LEVEL_RECORD_ID,
            disposition=DISPOSITION_SKIPPED,
            reason="Upstream dependency 'flatten_code' failed",
        )
        assert backend.has_disposition(
            "action_a", DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID
        ), "pre-condition: stale SKIPPED@NODE_LEVEL must be present"

        executor._execute_action_run(_params())

        assert not backend.has_disposition(
            "action_a", DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID
        ), "stale SKIPPED@NODE_LEVEL must be cleared once the action begins executing"

    def test_prior_run_skipped_no_stale_warning_fires_on_current_run(self, tmp_path):
        """No 'Stale guard-skip disposition' warning fires on a rerun.

        The heal at ``_resolve_completion_status`` is unreachable because
        clear-on-execute already removed the stale row before
        ``_handle_run_success`` reached the resolver.
        """
        executor, backend = _make_executor_with_real_backend(tmp_path)

        backend.set_disposition(
            action_name="action_a",
            record_id=NODE_LEVEL_RECORD_ID,
            disposition=DISPOSITION_SKIPPED,
            reason="Upstream dependency 'flatten_code' failed",
        )
        # Simulate the action producing per-record output this round —
        # ``_resolve_completion_status`` only enters the (pre-fix) heal branch
        # when ``list_target_files`` is non-empty. Use ``_write_target_raw``
        # directly to bypass delta-extraction bootstrapping.
        backend._write_target_raw("action_a", "out.json", [{"source_guid": "guid-1", "x": 1}])

        # Attach a manual handler — pytest's caplog fixture does not reliably
        # capture records from module-level loggers configured after import,
        # so we drive the capture explicitly against the executor's logger.
        captured: list[str] = []

        class _Cap(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())

        exec_logger = logging.getLogger("agent_actions.workflow.executor")
        handler = _Cap(level=logging.WARNING)
        exec_logger.addHandler(handler)
        try:
            executor._execute_action_run(_params())
        finally:
            exec_logger.removeHandler(handler)

        stale = [m for m in captured if "Stale guard-skip disposition" in m]
        assert stale == [], (
            "clear-on-execute must make the heal unreachable — but the read-side "
            f"heal warning fired: {stale}"
        )

    def test_per_record_dispositions_survive_node_clear(self, tmp_path):
        """Per-record success dispositions written by a prior run must NOT be
        deleted by clear-on-execute — only NODE_LEVEL_RECORD_ID rows go."""
        executor, backend = _make_executor_with_real_backend(tmp_path)

        backend.set_disposition(
            action_name="action_a",
            record_id="real-source-guid-abc123",
            disposition=DISPOSITION_SUCCESS,
        )
        backend.set_disposition(
            action_name="action_a",
            record_id=NODE_LEVEL_RECORD_ID,
            disposition=DISPOSITION_SKIPPED,
            reason="prior round",
        )

        executor._execute_action_run(_params())

        assert backend.has_disposition(
            "action_a", DISPOSITION_SUCCESS, record_id="real-source-guid-abc123"
        ), "per-record disposition rows must survive clear-on-execute"
        assert not backend.has_disposition(
            "action_a", DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID
        )

    def test_dependency_skip_this_round_is_not_cleared(self, tmp_path):
        """In-round SKIPPED written by ``_handle_dependency_skip`` survives.

        Clear-on-execute lives INSIDE ``_execute_action_run``. The dependency-skip
        path exits ``execute_action_sync`` before reaching it, so the SKIPPED
        row it writes for the current round is not clobbered.
        """
        executor, backend = _make_executor_with_real_backend(tmp_path)

        # Force the dependency-skip path: upstream failed.
        executor.deps.state_manager.is_failed.side_effect = lambda dep: dep == "upstream"
        executor.deps.state_manager.get_status.return_value = ActionStatus.PENDING

        result = executor.execute_action_sync(
            "action_a",
            action_idx=0,
            action_config={"dependencies": ["upstream"]},
            is_last_action=False,
        )

        assert result.status == ActionStatus.SKIPPED, (
            "upstream-failed must route through _handle_dependency_skip"
        )
        assert backend.has_disposition(
            "action_a", DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID
        ), (
            "the SKIPPED@NODE_LEVEL row _handle_dependency_skip writes this round "
            "must survive — clear-on-execute only runs inside _execute_action_run"
        )
        executor.deps.action_runner.run_action.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_execute_also_clears(self, tmp_path):
        """Same scenario as the first test but via ``_execute_action_run_async``."""
        executor, backend = _make_executor_with_real_backend(tmp_path)

        backend.set_disposition(
            action_name="action_a",
            record_id=NODE_LEVEL_RECORD_ID,
            disposition=DISPOSITION_SKIPPED,
            reason="prior round",
        )

        await executor._execute_action_run_async(_params())

        assert not backend.has_disposition(
            "action_a", DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID
        ), "async _execute_action_run_async must clear stale NODE_LEVEL rows too"

    def test_storage_error_during_clear_propagates(self, tmp_path):
        """Clear failure must not be swallowed — a silently-caught failure would let a stale
        SKIPPED@NODE_LEVEL row survive, and the resolver would then misclassify a successful
        run as SKIPPED."""
        executor, backend = _make_executor_with_real_backend(tmp_path)

        broken_backend = MagicMock(wraps=backend)
        broken_backend.clear_disposition.side_effect = RuntimeError("simulated storage lock")
        executor.deps.action_runner.storage_backend = broken_backend

        with pytest.raises(RuntimeError, match="simulated storage lock"):
            executor._execute_action_run(_params())

        executor.deps.action_runner.run_action.assert_not_called()
