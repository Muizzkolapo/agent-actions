"""Tests for processing_recovery.py orchestration — must pass pre-refactor.

These tests exercise the real orchestration logic in processing_recovery.py:
- process_recovery_batch() dispatch on recovery_type
- handle_retry_recovery() state transitions
- handle_reprompt_recovery() graduated pool + resubmission
- finalize_batch_output() event + output + cleanup
- RecoveryState persistence between cycles

Mock boundaries: provider calls, disk I/O (RecoveryStateManager), event bus.
Do NOT mock internal functions — only external boundaries.
"""

from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.batch.services.processing_recovery import (
    finalize_batch_output,
    handle_reprompt_recovery,
    handle_retry_recovery,
    process_recovery_batch,
)
from agent_actions.llm.providers.batch_base import BatchResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(custom_id: str, content: str = "response", success: bool = True) -> BatchResult:
    return BatchResult(custom_id=custom_id, content=content, success=success)


def _make_entry(recovery_type: str = "retry", attempt: int = 1) -> BatchJobEntry:
    return BatchJobEntry(
        batch_id="batch-123",
        status=BatchStatus.SUBMITTED,
        timestamp="2026-05-01T00:00:00Z",
        provider="openai",
        record_count=3,
        file_name="test_file_retry_1",
        parent_file_name="test_file",
        recovery_type=recovery_type,
        recovery_attempt=attempt,
    )


def _make_state(phase: str = "retry", **kwargs) -> RecoveryState:
    defaults = {
        "retry_attempt": 1,
        "retry_max_attempts": 3,
        "missing_ids": ["id-1", "id-2"],
        "record_failure_counts": {"id-1": 1, "id-2": 1},
        "reprompt_attempt": 0,
        "reprompt_max_attempts": 2,
        "on_exhausted": "return_last",
        "accumulated_results": [],
        "graduated_results": [],
    }
    defaults.update(kwargs)
    return RecoveryState(phase=phase, **defaults)


def _mock_service():
    """Create a mock BatchProcessingService with required attributes."""
    service = MagicMock()
    service._retry_service = MagicMock()
    service._context_manager = MagicMock()
    service._client_resolver = MagicMock()
    service._storage_backend = MagicMock()
    service._action_name = "test_action"
    service._apply_workflow_session_id = MagicMock(return_value={"kind": "llm"})
    service._convert_batch_results_to_workflow_format = MagicMock(return_value=[])
    service._determine_output_path = MagicMock(return_value="/tmp/output.json")
    service._write_batch_output = MagicMock()
    service._cleanup_recovery_entries = MagicMock()
    service._update_prompt_trace_responses = MagicMock()
    return service


# ---------------------------------------------------------------------------
# TestProcessRecoveryBatchDispatch
# ---------------------------------------------------------------------------


class TestProcessRecoveryBatchDispatch:
    """process_recovery_batch() dispatches correctly on recovery_type."""

    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    @patch("agent_actions.llm.batch.services.processing_recovery.retrieve_and_reconcile")
    def test_retry_type_dispatches_to_handle_retry_recovery(self, mock_reconcile, mock_state_mgr):
        service = _mock_service()
        entry = _make_entry(recovery_type="retry")
        state = _make_state(phase="retry")
        mock_state_mgr.load.return_value = state
        mock_reconcile.return_value = [_make_result("id-1")]

        service._retry_service.process_retry_results.return_value = (
            [_make_result("id-1")],  # merged
            set(),  # no still_missing
            {},  # updated_counts
            [],  # dropped
        )

        with (
            patch(
                "agent_actions.llm.batch.services.processing_recovery.check_and_submit_reprompt",
                return_value=True,
            ),
            patch(
                "agent_actions.llm.batch.services.processing_recovery.finalize_batch_output",
                return_value="/tmp/output.json",
            ),
        ):
            result = process_recovery_batch(
                service,
                batch_id="batch-123",
                file_name="test_file_retry_1",
                entry=entry,
                output_directory="/tmp",
                agent_config={"kind": "llm"},
                manager=MagicMock(),
                action_name="test_action",
            )

        assert result == "/tmp/output.json"
        service._retry_service.process_retry_results.assert_called_once()

    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    @patch("agent_actions.llm.batch.services.processing_recovery.retrieve_and_reconcile")
    def test_reprompt_type_dispatches_to_handle_reprompt_recovery(
        self, mock_reconcile, mock_state_mgr
    ):
        service = _mock_service()
        entry = _make_entry(recovery_type="reprompt")
        state = _make_state(phase="reprompt", reprompt_attempt=1)
        mock_state_mgr.load.return_value = state
        mock_reconcile.return_value = [_make_result("id-1")]

        with (
            patch(
                "agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop",
                return_value=None,
            ),
            patch(
                "agent_actions.llm.batch.services.processing_recovery.finalize_batch_output",
                return_value="/tmp/output.json",
            ),
        ):
            result = process_recovery_batch(
                service,
                batch_id="batch-123",
                file_name="test_file_reprompt_1",
                entry=entry,
                output_directory="/tmp",
                agent_config={"kind": "llm"},
                manager=MagicMock(),
                action_name="test_action",
            )

        assert result == "/tmp/output.json"
        service._retry_service.process_retry_results.assert_not_called()

    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    @patch("agent_actions.llm.batch.services.processing_recovery.retrieve_and_reconcile")
    def test_unknown_type_returns_none(self, mock_reconcile, mock_state_mgr):
        service = _mock_service()
        entry = _make_entry(recovery_type="unknown")
        state = _make_state(phase="retry")
        mock_state_mgr.load.return_value = state
        mock_reconcile.return_value = []

        result = process_recovery_batch(
            service,
            batch_id="batch-123",
            file_name="test_file",
            entry=entry,
            output_directory="/tmp",
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            action_name="test_action",
        )

        assert result is None

    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    def test_missing_state_returns_none(self, mock_state_mgr):
        service = _mock_service()
        entry = _make_entry(recovery_type="retry")
        mock_state_mgr.load.return_value = None

        result = process_recovery_batch(
            service,
            batch_id="batch-123",
            file_name="test_file",
            entry=entry,
            output_directory="/tmp",
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            action_name="test_action",
        )

        assert result is None


# ---------------------------------------------------------------------------
# TestHandleRetryRecovery
# ---------------------------------------------------------------------------


class TestHandleRetryRecovery:
    """handle_retry_recovery() state transitions."""

    def test_still_missing_submits_next_retry_batch(self):
        """When IDs are still missing and attempts remain, submit another retry."""
        service = _mock_service()
        state = _make_state(phase="retry", retry_attempt=1, retry_max_attempts=3)
        manager = MagicMock()

        service._retry_service.process_retry_results.return_value = (
            [_make_result("id-1")],  # merged
            {"id-2"},  # still_missing
            {"id-2": 2},  # updated_counts
            [],
        )
        service._retry_service.submit_retry_batch.return_value = ("new-batch-id", 1)

        with patch(
            "agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager"
        ) as mock_mgr:
            result = handle_retry_recovery(
                service,
                state=state,
                recovery_results=[_make_result("id-1")],
                accumulated=[],
                context_map={},
                output_directory="/tmp",
                parent_file_name="test_file",
                entry=_make_entry(),
                agent_config={"kind": "llm"},
                manager=manager,
                provider=MagicMock(),
                action_name="test_action",
                start_time=0.0,
            )

        assert result is None  # More retries pending
        assert state.retry_attempt == 2
        assert state.missing_ids == ["id-2"]
        mock_mgr.save.assert_called_once()
        manager.save_batch_job.assert_called_once()

    @patch("agent_actions.llm.batch.services.processing_recovery.fire_event")
    @patch("agent_actions.llm.batch.services.processing_recovery.write_record_dispositions")
    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    def test_retry_exhausted_transitions_to_reprompt_phase(
        self, mock_build_loop, _disp, mock_fire_event
    ):
        """When retries exhausted, runs check_and_submit_reprompt for real (phase transition).

        This exercises the actual transition — not a mock of it. We let
        check_and_submit_reprompt run through with build_evaluation_loop returning
        a loop that graduates everything, so it finalizes immediately.
        """
        service = _mock_service()
        state = _make_state(
            phase="retry",
            retry_attempt=3,
            retry_max_attempts=3,
            missing_ids=["id-2"],
        )

        service._retry_service.process_retry_results.return_value = (
            [_make_result("id-1")],
            {"id-2"},  # still_missing after max retries
            {"id-2": 3},
            [],
        )
        service._retry_service.build_exhausted_recovery.return_value = {"id-2": MagicMock()}

        # build_evaluation_loop returns a loop where all records graduate
        loop = MagicMock()
        strategy = MagicMock()
        strategy.name = "validation"
        strategy.max_attempts = 2
        strategy.on_exhausted = "return_last"
        loop.split.return_value = ([_make_result("id-1")], [])  # all pass
        mock_build_loop.return_value = (loop, strategy, None)

        with patch(
            "agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager"
        ) as mock_mgr:
            result = handle_retry_recovery(
                service,
                state=state,
                recovery_results=[_make_result("id-1")],
                accumulated=[],
                context_map={},
                output_directory="/tmp",
                parent_file_name="test_file",
                entry=_make_entry(),
                agent_config={"kind": "llm"},
                manager=MagicMock(),
                provider=MagicMock(),
                action_name="test_action",
                start_time=0.0,
            )

        # Observable: phase transition happened (reprompt ran), then finalized
        assert result == "/tmp/output.json"
        service._write_batch_output.assert_called_once()
        # build_exhausted_recovery was called with the still_missing IDs
        service._retry_service.build_exhausted_recovery.assert_called_once_with(
            {"id-2"}, {"id-2": 3}
        )
        # Recovery state was deleted (finalization completed)
        mock_mgr.delete.assert_called_once()

    @patch("agent_actions.llm.batch.services.processing_recovery.fire_event")
    @patch("agent_actions.llm.batch.services.processing_recovery.write_record_dispositions")
    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    def test_all_recovered_finalizes_with_event_and_status(
        self, mock_build_loop, _disp, mock_fire_event
    ):
        """All recovered + no reprompt: writes output, fires event with correct counts."""
        service = _mock_service()
        state = _make_state(phase="retry", retry_attempt=1, missing_ids=[])
        manager = MagicMock()

        service._retry_service.process_retry_results.return_value = (
            [_make_result("id-1"), _make_result("id-2")],
            set(),  # nothing missing
            {},
            [],
        )
        mock_build_loop.return_value = None  # no reprompt configured

        with patch(
            "agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager"
        ) as mock_mgr:
            result = handle_retry_recovery(
                service,
                state=state,
                recovery_results=[_make_result("id-1"), _make_result("id-2")],
                accumulated=[],
                context_map={},
                output_directory="/tmp",
                parent_file_name="test_file",
                entry=_make_entry(),
                agent_config={"kind": "llm"},
                manager=manager,
                provider=MagicMock(),
                action_name="test_action",
                start_time=0.0,
            )

        # Observable: output written, event fired with correct payload, state cleaned
        assert result == "/tmp/output.json"
        service._write_batch_output.assert_called_once()
        mock_fire_event.assert_called_once()
        event = mock_fire_event.call_args[0][0]
        assert event.total == 2
        assert event.completed == 2
        assert event.failed == 0
        mock_mgr.delete.assert_called_once_with("/tmp", "test_file")
        manager.update_status.assert_called_once_with("batch-123", BatchStatus.COMPLETED)


# ---------------------------------------------------------------------------
# TestHandleRepromptRecovery
# ---------------------------------------------------------------------------


class TestHandleRepromptRecovery:
    """handle_reprompt_recovery() graduated pool + resubmission."""

    def _setup_eval_loop(self, graduated_ids, failing_ids):
        """Create mock evaluation loop that splits results by ID."""
        loop = MagicMock()
        strategy = MagicMock()
        strategy.name = "validation"
        strategy.max_attempts = 3
        strategy.on_exhausted = "return_last"

        graduated = [_make_result(cid) for cid in graduated_ids]
        failing = [_make_result(cid, success=False) for cid in failing_ids]
        loop.split.return_value = (graduated, failing)

        return loop, strategy

    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    def test_all_graduated_finalizes_output(self, mock_mgr, mock_build_loop):
        """When all records pass evaluation, finalize immediately."""
        loop, strategy = self._setup_eval_loop(["id-1", "id-2"], [])
        mock_build_loop.return_value = (loop, strategy, None)

        service = _mock_service()
        state = _make_state(phase="reprompt", reprompt_attempt=1)

        with patch(
            "agent_actions.llm.batch.services.processing_recovery.finalize_batch_output",
            return_value="/tmp/output.json",
        ) as mock_finalize:
            result = handle_reprompt_recovery(
                service,
                state=state,
                recovery_results=[_make_result("id-1"), _make_result("id-2")],
                accumulated=[],
                context_map={},
                output_directory="/tmp",
                parent_file_name="test_file",
                entry=_make_entry(recovery_type="reprompt"),
                agent_config={"kind": "llm"},
                manager=MagicMock(),
                provider=MagicMock(),
                action_name="test_action",
                start_time=0.0,
            )

        assert result == "/tmp/output.json"
        mock_finalize.assert_called_once()
        mock_mgr.delete.assert_called_once()

    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    def test_still_failing_submits_next_reprompt(self, mock_mgr, mock_build_loop):
        """When records still fail and attempts remain, submit next reprompt."""
        loop, strategy = self._setup_eval_loop(["id-1"], ["id-2"])
        mock_build_loop.return_value = (loop, strategy, None)

        service = _mock_service()
        state = _make_state(phase="reprompt", reprompt_attempt=1, reprompt_max_attempts=3)
        manager = MagicMock()

        service._retry_service.submit_reprompt_batch.return_value = ("reprompt-batch-2", 1)

        result = handle_reprompt_recovery(
            service,
            state=state,
            recovery_results=[_make_result("id-1"), _make_result("id-2")],
            accumulated=[],
            context_map={},
            output_directory="/tmp",
            parent_file_name="test_file",
            entry=_make_entry(recovery_type="reprompt"),
            agent_config={"kind": "llm"},
            manager=manager,
            provider=MagicMock(),
            action_name="test_action",
            start_time=0.0,
        )

        assert result is None  # More reprompts pending
        assert state.reprompt_attempt == 2
        mock_mgr.save.assert_called_once()
        manager.save_batch_job.assert_called_once()

    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    def test_exhausted_applies_exhaustion_metadata(self, mock_mgr, mock_build_loop):
        """When attempts exhausted, applies exhaustion metadata and finalizes."""
        loop, strategy = self._setup_eval_loop(["id-1"], ["id-2"])
        mock_build_loop.return_value = (loop, strategy, None)

        service = _mock_service()
        # reprompt_attempt == max → exhausted
        state = _make_state(phase="reprompt", reprompt_attempt=2, reprompt_max_attempts=2)

        with patch(
            "agent_actions.llm.batch.services.processing_recovery.finalize_batch_output",
            return_value="/tmp/output.json",
        ):
            result = handle_reprompt_recovery(
                service,
                state=state,
                recovery_results=[_make_result("id-1"), _make_result("id-2")],
                accumulated=[],
                context_map={},
                output_directory="/tmp",
                parent_file_name="test_file",
                entry=_make_entry(recovery_type="reprompt"),
                agent_config={"kind": "llm"},
                manager=MagicMock(),
                provider=MagicMock(),
                action_name="test_action",
                start_time=0.0,
            )

        assert result == "/tmp/output.json"
        service._retry_service.apply_exhausted_reprompt_metadata.assert_called_once()

    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    def test_graduated_results_accumulated_in_state(self, mock_mgr, mock_build_loop):
        """Graduated results from each cycle are accumulated in state."""
        loop, strategy = self._setup_eval_loop(["id-1"], ["id-2"])
        mock_build_loop.return_value = (loop, strategy, None)

        service = _mock_service()
        state = _make_state(phase="reprompt", reprompt_attempt=1, reprompt_max_attempts=3)
        # Pre-existing graduated from previous cycle
        state.graduated_results = [{"custom_id": "id-0", "content": "old", "success": True}]

        service._retry_service.submit_reprompt_batch.return_value = ("reprompt-batch", 1)

        handle_reprompt_recovery(
            service,
            state=state,
            recovery_results=[_make_result("id-1"), _make_result("id-2")],
            accumulated=[],
            context_map={},
            output_directory="/tmp",
            parent_file_name="test_file",
            entry=_make_entry(recovery_type="reprompt"),
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            provider=MagicMock(),
            action_name="test_action",
            start_time=0.0,
        )

        assert len(state.graduated_results) == 2  # 1 old + 1 new (id-1 graduated)


# ---------------------------------------------------------------------------
# TestFinalizeBatchOutput
# ---------------------------------------------------------------------------


class TestFinalizeBatchOutput:
    """finalize_batch_output() fires correct event and cleans up."""

    def _run_finalize(self, results=None, batch_id="batch-123"):
        """Run finalize_batch_output with standard args, return (service, manager, event)."""
        service = _mock_service()
        manager = MagicMock()
        if results is None:
            results = [_make_result("id-1"), _make_result("id-2", success=False)]

        with (
            patch("agent_actions.llm.batch.services.processing_recovery.fire_event") as mock_event,
            patch("agent_actions.llm.batch.services.processing_recovery.write_record_dispositions"),
        ):
            output_path = finalize_batch_output(
                service,
                batch_results=results,
                exhausted_recovery=None,
                context_map={},
                output_directory="/tmp",
                file_name="test_file",
                batch_id=batch_id,
                agent_config={"kind": "llm"},
                manager=manager,
                action_name="test_action",
                start_time=0.0,
            )

        event = mock_event.call_args[0][0]
        return service, manager, event, output_path

    def test_event_payload_reflects_success_and_failure_counts(self):
        """Event: total/completed/failed derived from actual batch results."""
        _, _, event, _ = self._run_finalize(
            results=[_make_result("id-1"), _make_result("id-2", success=False)]
        )
        assert event.batch_id == "batch-123"
        assert event.total == 2
        assert event.completed == 1
        assert event.failed == 1

    def test_output_path_returned_and_file_written(self):
        service, _, _, output_path = self._run_finalize()
        assert output_path == "/tmp/output.json"
        service._write_batch_output.assert_called_once()

    def test_manager_marked_completed(self):
        _, manager, _, _ = self._run_finalize(batch_id="batch-789")
        manager.update_status.assert_called_once_with("batch-789", BatchStatus.COMPLETED)

    def test_finalize_does_not_handle_recovery_cleanup(self):
        """Cleanup is the caller's responsibility — finalize only does processing."""
        service, _, _, _ = self._run_finalize()
        service._cleanup_recovery_entries.assert_not_called()


# ---------------------------------------------------------------------------
# TestRecoveryStatePersistence
# ---------------------------------------------------------------------------


class TestRecoveryStatePersistence:
    """RecoveryState loaded and saved correctly between cycles."""

    def test_attempt_counters_increment_on_retry(self):
        """Retry attempt counter increments when submitting next retry batch."""
        service = _mock_service()
        state = _make_state(phase="retry", retry_attempt=1, retry_max_attempts=3)

        service._retry_service.process_retry_results.return_value = (
            [],
            {"id-1"},
            {"id-1": 2},
            [],
        )
        service._retry_service.submit_retry_batch.return_value = ("new-batch", 1)

        with patch(
            "agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager"
        ) as mock_mgr:
            handle_retry_recovery(
                service,
                state=state,
                recovery_results=[],
                accumulated=[],
                context_map={},
                output_directory="/tmp",
                parent_file_name="test_file",
                entry=_make_entry(),
                agent_config={"kind": "llm"},
                manager=MagicMock(),
                provider=MagicMock(),
                action_name="test_action",
                start_time=0.0,
            )

        assert state.retry_attempt == 2
        mock_mgr.save.assert_called_once()

    @patch("agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop")
    @patch("agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager")
    def test_reprompt_attempt_increments_on_resubmit(self, mock_mgr, mock_build_loop):
        """Reprompt attempt counter increments when submitting next reprompt."""
        loop = MagicMock()
        strategy = MagicMock()
        strategy.name = "validation"
        loop.split.return_value = ([], [_make_result("id-1")])  # all failing
        mock_build_loop.return_value = (loop, strategy, None)

        service = _mock_service()
        state = _make_state(phase="reprompt", reprompt_attempt=1, reprompt_max_attempts=3)
        service._retry_service.submit_reprompt_batch.return_value = ("reprompt-batch", 1)

        handle_reprompt_recovery(
            service,
            state=state,
            recovery_results=[_make_result("id-1")],
            accumulated=[],
            context_map={},
            output_directory="/tmp",
            parent_file_name="test_file",
            entry=_make_entry(recovery_type="reprompt"),
            agent_config={"kind": "llm"},
            manager=MagicMock(),
            provider=MagicMock(),
            action_name="test_action",
            start_time=0.0,
        )

        assert state.reprompt_attempt == 2
        mock_mgr.save.assert_called_once()
