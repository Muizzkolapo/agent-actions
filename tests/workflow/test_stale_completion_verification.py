"""Regression tests for issue #1224 — parallel actions fail when upstream is
'completed' in the status file but has no output in the SQLite storage backend.

Root cause: execute_level_async filtered out 'completed' actions via
get_pending_actions() before dispatching them, so _verify_completion_status
inside execute_action_async was never reached.  Stale completions (e.g. after
a DB clear or backend swap) were silently skipped, leaving downstream actions
unable to find upstream data.

Fix:
  1. execute_level_async now verifies all completed actions in a level before
     calling get_pending_actions, resetting stale ones to 'pending'.
  2. coordinator._run_single_action does the same for the sequential path.
  3. SQLiteBackend read methods hold self._lock for thread-safety during
     parallel sibling execution (list_target_files, read_target, read_source,
     list_source_files, get_disposition, has_disposition, preview_target,
     get_storage_stats).
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor(storage_has_data: bool) -> ActionExecutor:
    """Build an ActionExecutor whose storage backend returns data or not."""
    state_manager = MagicMock()
    action_runner = MagicMock()
    storage_backend = MagicMock()
    storage_backend.list_target_files.return_value = ["output.json"] if storage_has_data else []
    storage_backend.has_disposition.return_value = False
    action_runner.storage_backend = storage_backend

    deps = ExecutorDependencies(
        action_runner=action_runner,
        state_manager=state_manager,
        skip_evaluator=MagicMock(),
        batch_manager=MagicMock(),
        output_manager=MagicMock(),
    )
    return ActionExecutor(deps=deps)


# ---------------------------------------------------------------------------
# ActionExecutor.verify_completion_status
# ---------------------------------------------------------------------------


class TestVerifyCompletionStatus:
    """Public wrapper around _verify_completion_status — used by execute_level_async."""

    def test_returns_true_when_storage_has_data(self):
        """Action with SQLite output is genuinely complete — skip it."""
        executor = _make_executor(storage_has_data=True)
        result = executor.verify_completion_status("write_description")
        assert result is True
        executor.deps.state_manager.update_status.assert_not_called()

    def test_returns_false_and_resets_to_pending_when_storage_empty(self):
        """Stale completion (no SQLite data) → reset to 'pending' for re-run."""
        executor = _make_executor(storage_has_data=False)
        result = executor.verify_completion_status("write_description")
        assert result is False
        executor.deps.state_manager.update_status.assert_called_once_with(
            "write_description", "pending"
        )

    def test_returns_false_when_storage_backend_raises(self):
        """Any error during verification → conservative reset to pending."""
        executor = _make_executor(storage_has_data=True)
        executor.deps.action_runner.storage_backend.list_target_files.side_effect = RuntimeError(
            "connection error"
        )
        result = executor.verify_completion_status("write_description")
        assert result is False
        executor.deps.state_manager.update_status.assert_called_once_with(
            "write_description", "pending"
        )

    def test_returns_true_when_no_storage_backend(self):
        """No backend configured → trust the status file."""
        executor = _make_executor(storage_has_data=False)
        executor.deps.action_runner.storage_backend = None
        result = executor.verify_completion_status("write_description")
        assert result is True
        executor.deps.state_manager.update_status.assert_not_called()


# ---------------------------------------------------------------------------
# execute_level_async — verification before get_pending_actions
# ---------------------------------------------------------------------------


class TestExecuteLevelAsyncVerification:
    """execute_level_async must verify completed actions before deciding to skip."""

    @pytest.mark.asyncio
    async def test_stale_completed_action_is_reset_and_re_run(self):
        """
        Regression for issue #1224: if write_description is 'completed' but has no
        SQLite output, execute_level_async must reset it to 'pending' and dispatch it
        rather than silently skipping the entire level.
        """
        from agent_actions.workflow.parallel.action_executor import (
            ActionLevelOrchestrator,
            LevelExecutionParams,
        )

        # State manager: write_description starts as "completed", transitions to "pending"
        status = {"write_description": "completed"}

        state_manager = MagicMock()
        state_manager.is_completed.side_effect = lambda name: status.get(name) == "completed"
        state_manager.get_pending_actions.side_effect = lambda actions: [
            a for a in actions if status.get(a) != "completed"
        ]
        state_manager.get_batch_submitted_actions.return_value = []
        state_manager.get_failed_actions.return_value = []

        # Action executor: verify_completion_status resets write_description to pending
        action_executor = MagicMock()

        def _verify(name):
            status[name] = "pending"  # simulate reset
            return False  # stale — must re-run

        action_executor.verify_completion_status.side_effect = _verify

        # Capture which actions were dispatched
        dispatched: list[str] = []

        async def _fake_execute(action_name, **_):
            dispatched.append(action_name)
            from agent_actions.workflow.executor import ActionExecutionResult, ExecutionMetrics

            return ActionExecutionResult(
                success=True, status="completed", metrics=ExecutionMetrics()
            )

        action_executor.execute_action_async.side_effect = _fake_execute

        orchestrator = ActionLevelOrchestrator(
            execution_order=["write_description"],
            action_configs={"write_description": {"agent_type": "write_description"}},
            console=MagicMock(),
        )

        params = LevelExecutionParams(
            level_idx=0,
            level_actions=["write_description"],
            action_indices={"write_description": 0},
            state_manager=state_manager,
            action_executor=action_executor,
            concurrency_limit=5,
        )

        level_complete = await orchestrator.execute_level_async(params)

        assert level_complete is True
        # verify_completion_status must have been called for the completed action
        action_executor.verify_completion_status.assert_called_once_with("write_description")
        # After reset, the action must have been dispatched
        assert "write_description" in dispatched

    @pytest.mark.asyncio
    async def test_genuinely_complete_level_is_skipped(self):
        """Level where all actions are genuinely complete (with SQLite data) is skipped."""
        from agent_actions.workflow.parallel.action_executor import (
            ActionLevelOrchestrator,
            LevelExecutionParams,
        )

        state_manager = MagicMock()
        state_manager.is_completed.return_value = True
        state_manager.get_pending_actions.return_value = []  # still empty after verification
        state_manager.get_batch_submitted_actions.return_value = []
        state_manager.get_failed_actions.return_value = []

        action_executor = MagicMock()
        action_executor.verify_completion_status.return_value = True  # data present

        orchestrator = ActionLevelOrchestrator(
            execution_order=["write_description"],
            action_configs={"write_description": {"agent_type": "write_description"}},
            console=MagicMock(),
        )

        params = LevelExecutionParams(
            level_idx=0,
            level_actions=["write_description"],
            action_indices={"write_description": 0},
            state_manager=state_manager,
            action_executor=action_executor,
            concurrency_limit=5,
        )

        level_complete = await orchestrator.execute_level_async(params)

        assert level_complete is True
        # Verification ran, found data → nothing dispatched
        action_executor.verify_completion_status.assert_called_once_with("write_description")
        action_executor.execute_action_async.assert_not_called()


# ---------------------------------------------------------------------------
# SQLiteBackend thread-safe reads
# ---------------------------------------------------------------------------


class TestSQLiteBackendThreadSafeReads:
    """list_target_files and read_target hold self._lock during the query."""

    def test_list_target_files_acquires_lock(self, tmp_path):
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        backend = SQLiteBackend(str(tmp_path / "test.db"), "test_workflow")
        backend.initialize()
        backend.write_target("action_a", "out.json", [{"id": 1}])

        acquired = []
        original_lock = backend._lock

        class TrackingLock:
            def __enter__(self_inner):
                acquired.append("locked")
                return original_lock.__enter__()

            def __exit__(self_inner, *args):
                return original_lock.__exit__(*args)

        with patch.object(backend, "_lock", TrackingLock()):
            backend.list_target_files("action_a")

        assert "locked" in acquired, "list_target_files must acquire _lock"

    def test_read_target_acquires_lock(self, tmp_path):
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        backend = SQLiteBackend(str(tmp_path / "test.db"), "test_workflow")
        backend.initialize()
        backend.write_target("action_a", "out.json", [{"id": 1}])

        acquired = []
        original_lock = backend._lock

        class TrackingLock:
            def __enter__(self_inner):
                acquired.append("locked")
                return original_lock.__enter__()

            def __exit__(self_inner, *args):
                return original_lock.__exit__(*args)

        with patch.object(backend, "_lock", TrackingLock()):
            backend.read_target("action_a", "out.json")

        assert "locked" in acquired, "read_target must acquire _lock"

    def test_concurrent_reads_return_correct_data(self, tmp_path):
        """Multiple threads reading simultaneously must all return correct data."""
        import concurrent.futures

        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        backend = SQLiteBackend(str(tmp_path / "test.db"), "test_workflow")
        backend.initialize()
        backend.write_target("upstream", "data.json", [{"val": i} for i in range(50)])

        results: list[list[str]] = []
        errors: list[Exception] = []

        def read_files():
            try:
                results.append(backend.list_target_files("upstream"))
            except Exception as exc:
                errors.append(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(read_files) for _ in range(20)]
            concurrent.futures.wait(futures)

        assert not errors, f"Concurrent reads raised: {errors}"
        assert all(r == ["data.json"] for r in results), "All threads must see correct data"


# ---------------------------------------------------------------------------
# SQLiteBackend — lock-acquisition for remaining read methods
# ---------------------------------------------------------------------------


def _make_tracking_lock(backend):
    """Return (TrackingLock, acquired_list) for patching backend._lock."""
    acquired: list[str] = []
    original = backend._lock

    class TrackingLock:
        def __enter__(self_inner):
            acquired.append("locked")
            return original.__enter__()

        def __exit__(self_inner, *args):
            return original.__exit__(*args)

    return TrackingLock(), acquired


class TestSQLiteBackendRemainingReadLocks:
    """read_source, list_source_files, get_disposition, has_disposition,
    preview_target, and get_storage_stats must all acquire self._lock."""

    def _setup_backend(self, tmp_path):
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        backend = SQLiteBackend(str(tmp_path / "test.db"), "test_workflow")
        backend.initialize()
        return backend

    def test_read_source_acquires_lock(self, tmp_path):
        backend = self._setup_backend(tmp_path)
        backend.write_source("in.json", [{"source_guid": "abc", "val": 1}])

        tracking_lock, acquired = _make_tracking_lock(backend)
        with patch.object(backend, "_lock", tracking_lock):
            backend.read_source("in.json")

        assert "locked" in acquired, "read_source must acquire _lock"

    def test_list_source_files_acquires_lock(self, tmp_path):
        backend = self._setup_backend(tmp_path)
        backend.write_source("in.json", [{"source_guid": "abc", "val": 1}])

        tracking_lock, acquired = _make_tracking_lock(backend)
        with patch.object(backend, "_lock", tracking_lock):
            backend.list_source_files()

        assert "locked" in acquired, "list_source_files must acquire _lock"

    def test_get_disposition_acquires_lock(self, tmp_path):
        backend = self._setup_backend(tmp_path)
        backend.set_disposition("action_a", "rec1", "skipped")

        tracking_lock, acquired = _make_tracking_lock(backend)
        with patch.object(backend, "_lock", tracking_lock):
            backend.get_disposition("action_a")

        assert "locked" in acquired, "get_disposition must acquire _lock"

    def test_has_disposition_acquires_lock(self, tmp_path):
        backend = self._setup_backend(tmp_path)
        backend.set_disposition("action_a", "rec1", "skipped")

        tracking_lock, acquired = _make_tracking_lock(backend)
        with patch.object(backend, "_lock", tracking_lock):
            backend.has_disposition("action_a", "skipped")

        assert "locked" in acquired, "has_disposition must acquire _lock"

    def test_preview_target_acquires_lock(self, tmp_path):
        backend = self._setup_backend(tmp_path)
        backend.write_target("action_a", "out.json", [{"id": 1}])

        tracking_lock, acquired = _make_tracking_lock(backend)
        with patch.object(backend, "_lock", tracking_lock):
            backend.preview_target("action_a")

        assert "locked" in acquired, "preview_target must acquire _lock"

    def test_get_storage_stats_acquires_lock(self, tmp_path):
        backend = self._setup_backend(tmp_path)
        backend.write_target("action_a", "out.json", [{"id": 1}])

        tracking_lock, acquired = _make_tracking_lock(backend)
        with patch.object(backend, "_lock", tracking_lock):
            backend.get_storage_stats()

        assert "locked" in acquired, "get_storage_stats must acquire _lock"


# ---------------------------------------------------------------------------
# execute_level_async — mixed completed/pending level
# ---------------------------------------------------------------------------


class TestExecuteLevelAsyncMixedLevel:
    """verify_completion_status is only called for actions that are 'completed',
    not for pending ones in the same level."""

    @pytest.mark.asyncio
    async def test_only_completed_actions_are_verified(self):
        from agent_actions.workflow.parallel.action_executor import (
            ActionLevelOrchestrator,
            LevelExecutionParams,
        )

        # action_a is completed with valid data; action_b is pending
        status = {"action_a": "completed", "action_b": "pending"}

        state_manager = MagicMock()
        state_manager.is_completed.side_effect = lambda name: status.get(name) == "completed"
        state_manager.get_pending_actions.side_effect = lambda actions: [
            a for a in actions if status.get(a) != "completed"
        ]
        state_manager.get_batch_submitted_actions.return_value = []
        state_manager.get_failed_actions.return_value = []

        action_executor = MagicMock()
        # action_a has valid storage data — skip it
        action_executor.verify_completion_status.return_value = True

        dispatched: list[str] = []

        async def _fake_execute(action_name, **_):
            dispatched.append(action_name)
            from agent_actions.workflow.executor import ActionExecutionResult, ExecutionMetrics

            return ActionExecutionResult(
                success=True, status="completed", metrics=ExecutionMetrics()
            )

        action_executor.execute_action_async.side_effect = _fake_execute

        orchestrator = ActionLevelOrchestrator(
            execution_order=["action_a", "action_b"],
            action_configs={
                "action_a": {"agent_type": "action_a"},
                "action_b": {"agent_type": "action_b"},
            },
            console=MagicMock(),
        )

        params = LevelExecutionParams(
            level_idx=0,
            level_actions=["action_a", "action_b"],
            action_indices={"action_a": 0, "action_b": 1},
            state_manager=state_manager,
            action_executor=action_executor,
            concurrency_limit=5,
        )

        level_complete = await orchestrator.execute_level_async(params)

        assert level_complete is True
        # verify_completion_status called only for the completed action
        action_executor.verify_completion_status.assert_called_once_with("action_a")
        # Only the pending action was dispatched
        assert dispatched == ["action_b"]


# ---------------------------------------------------------------------------
# coordinator._run_single_action — sequential verification path
# ---------------------------------------------------------------------------


class TestCoordinatorSequentialVerification:
    """_run_single_action must verify completed actions before skipping."""

    def _make_coordinator_mock(self, storage_has_data: bool):
        """Build a minimal AgentWorkflow-shaped mock for _run_single_action."""
        mock = MagicMock()
        mock.action_configs = {"write_description": {"agent_type": "write_description"}}
        mock.execution_order = ["write_description"]
        mock.services.core.state_manager.is_completed.return_value = True
        mock.services.core.action_executor.verify_completion_status.return_value = storage_has_data
        return mock

    def test_genuinely_complete_action_is_skipped(self):
        """Sequential coordinator skips action when storage has valid data."""
        from agent_actions.workflow.coordinator import AgentWorkflow

        mock = self._make_coordinator_mock(storage_has_data=True)
        result = AgentWorkflow._run_single_action(
            mock, idx=0, action_name="write_description", total_actions=1
        )

        assert result is False
        mock.services.core.action_executor.execute_action_sync.assert_not_called()
        mock.event_logger.log_action_skip.assert_called_once_with(0, "write_description", 1)

    def test_stale_completed_action_is_re_run(self):
        """Sequential coordinator re-runs action when storage has no data."""
        from agent_actions.workflow.coordinator import AgentWorkflow
        from agent_actions.workflow.executor import ActionExecutionResult, ExecutionMetrics

        mock = self._make_coordinator_mock(storage_has_data=False)
        mock.services.core.action_executor.execute_action_sync.return_value = ActionExecutionResult(
            success=True, status="completed", metrics=ExecutionMetrics()
        )

        result = AgentWorkflow._run_single_action(
            mock, idx=0, action_name="write_description", total_actions=1
        )

        assert result is False
        mock.services.core.action_executor.execute_action_sync.assert_called_once()
        mock.event_logger.log_action_skip.assert_not_called()
