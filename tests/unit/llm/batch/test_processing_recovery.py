"""Tests for processing_recovery.py orchestration — must pass pre-refactor.

These tests exercise the real orchestration logic in processing_recovery.py:
- process_recovery_batch() dispatch on recovery_type
- handle_retry_recovery() state transitions
- finalize_batch_output() event + output + cleanup
- RecoveryState persistence between cycles

Mock boundaries: provider calls, disk I/O (RecoveryStateManager), event bus.
Do NOT mock internal functions — only external boundaries.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import (
    BatchIdentity,
    BatchJobEntry,
    BatchRegistryStats,
    RecoveryContext,
)
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.processing_recovery import (
    finalize_batch_output,
    handle_retry_recovery,
    process_recovery_batch,
)
from agent_actions.llm.providers.batch_base import BatchResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(custom_id: str, content: str = "response", success: bool = True) -> BatchResult:
    return BatchResult(custom_id=custom_id, content=content, success=success)


def _make_entry(
    recovery_type: str = "retry",
    attempt: int = 1,
    *,
    batch_id: str = "batch-123",
    file_name: str | None = None,
    parent_file_name: str = "test_file",
    record_count: int = 3,
    status: str = BatchStatus.SUBMITTED,
) -> BatchJobEntry:
    if file_name is None:
        file_name = f"{parent_file_name}_{recovery_type}_{attempt}"
    return BatchJobEntry(
        batch_id=batch_id,
        status=status,
        timestamp="2026-05-01T00:00:00Z",
        provider="openai",
        record_count=record_count,
        file_name=file_name,
        parent_file_name=parent_file_name,
        recovery_type=recovery_type,
        recovery_attempt=attempt,
    )


def _make_state(phase: str = "retry", **kwargs) -> RecoveryState:
    defaults = {
        "retry_attempt": 1,
        "retry_max_attempts": 3,
        "missing_ids": ["id-1", "id-2"],
        "record_failure_counts": {"id-1": 1, "id-2": 1},
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
    # returns the halt to raise after the write, or None
    service._context_manager = MagicMock()
    service._client_resolver = MagicMock()
    service._storage_backend = MagicMock()
    service._workflow_name = "test_action"
    service._resolve_action_name = lambda override=None: override or service._workflow_name
    service._apply_workflow_session_id = MagicMock(return_value={"kind": "llm"})
    service._convert_batch_results_to_workflow_format = MagicMock(return_value=([], None, None))
    service._determine_output_path = MagicMock(return_value=Path("/tmp/output.json"))
    service._write_batch_output = MagicMock()
    service._cleanup_recovery_entries = MagicMock()
    service._update_prompt_trace_responses = MagicMock()
    return service


def _make_context_and_identity(
    service=None,
    entry=None,
    manager=None,
    provider=None,
    agent_config=None,
    output_directory="/tmp",
    action_name="test_action",
    start_time=0.0,
    file_name="test_file",
    batch_id="batch-123",
):
    """Construct a (RecoveryContext, BatchIdentity) pair for tests."""
    if service is None:
        service = _mock_service()
    if entry is None:
        entry = _make_entry()
    if manager is None:
        manager = MagicMock()
    if provider is None:
        provider = MagicMock()
    if agent_config is None:
        agent_config = {"kind": "llm"}

    context = RecoveryContext(
        service=service,
        manager=manager,
        provider=provider,
        agent_config=agent_config,
        output_directory=output_directory,
        action_name=action_name,
        start_time=start_time,
    )
    identity = BatchIdentity(
        batch_id=batch_id,
        file_name=file_name,
        entry=entry,
    )
    return context, identity


# ---------------------------------------------------------------------------
# TestProcessRecoveryBatchDispatch
# ---------------------------------------------------------------------------


class TestProcessRecoveryBatchDispatch:
    """process_recovery_batch() dispatches correctly on recovery_type."""

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

        ctx, ident = _make_context_and_identity(
            service=service, manager=manager, file_name="test_file"
        )

        with patch(
            "agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager"
        ) as mock_mgr:
            result = handle_retry_recovery(
                ctx,
                ident,
                state=state,
                recovery_results=[_make_result("id-1")],
                accumulated=[],
                context_map={},
            )

        assert result is None  # More retries pending
        assert state.retry_attempt == 2
        assert state.missing_ids == ["id-2"]
        mock_mgr.save.assert_called_once()
        # Verify _register_recovery_batch produced correct BatchJobEntry
        save_args = manager.save_batch_job.call_args[0]
        assert save_args[0] == "test_file_retry_2"  # {parent}_{type}_{attempt}
        entry = save_args[1]
        assert entry.batch_id == "new-batch-id"
        assert entry.recovery_type == "retry"
        assert entry.recovery_attempt == 2
        assert entry.parent_file_name == "test_file"
        assert entry.record_count == 1
        assert entry.status == BatchStatus.SUBMITTED

    @patch("agent_actions.llm.batch.services.processing_recovery.fire_event")
    def test_all_recovered_finalizes_with_event_and_status(self, mock_fire_event):
        """All recovered: writes output, fires event with correct counts."""
        service = _mock_service()
        state = _make_state(phase="retry", retry_attempt=1, missing_ids=[])
        manager = MagicMock()

        service._retry_service.process_retry_results.return_value = (
            [_make_result("id-1"), _make_result("id-2")],
            set(),  # nothing missing
            {},
            [],
        )

        ctx, ident = _make_context_and_identity(
            service=service, manager=manager, file_name="test_file"
        )

        with patch(
            "agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager"
        ) as mock_mgr:
            result = handle_retry_recovery(
                ctx,
                ident,
                state=state,
                recovery_results=[_make_result("id-1"), _make_result("id-2")],
                accumulated=[],
                context_map={},
            )

        # Observable: output written, event fired with correct payload, state cleaned
        assert result == "/tmp/output.json"
        service._write_batch_output.assert_called_once()
        mock_fire_event.assert_called_once()
        event = mock_fire_event.call_args[0][0]
        assert event.total == 2
        assert event.completed == 2
        assert event.failed == 0
        mock_mgr.delete.assert_called_once()
        delete_args = mock_mgr.delete.call_args[0]
        assert delete_args[2] == "test_file"  # (backend, action_name, file_name)
        manager.update_status.assert_called_once_with("batch-123", BatchStatus.COMPLETED)


# ---------------------------------------------------------------------------
# TestHandleRepromptRecovery
# ---------------------------------------------------------------------------


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

        ctx, ident = _make_context_and_identity(
            service=service, manager=manager, batch_id=batch_id, file_name="test_file"
        )

        with (
            patch("agent_actions.llm.batch.services.processing_recovery.fire_event") as mock_event,
        ):
            output_path = finalize_batch_output(
                ctx,
                ident,
                batch_results=results,
                context_map={},
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

    def test_finalize_writes_filtered_dispositions(self):
        """Phase 7b parity: FILTERED records in context_map must reach DISPOSITION_FILTERED.

        finalize_batch_output is the production retrieve entry point (called via
        process_all_batch_results → _process_single_batch_file → _process_original_batch
        → _finalize_batch_output). The reconciler strips FILTERED rows from
        processed_data before this function runs, so the collector path never sees
        them. Without an explicit _write_filtered_dispositions call here, FILTERED
        records stay stuck at DISPOSITION_DEFERRED (stamped at submit by Phase 7a)
        and never transition to DISPOSITION_FILTERED — silently breaking the
        Phase 7b parity contract for every real batch run.
        """
        service = _mock_service()
        manager = MagicMock()
        context_map = {"custom-filtered-1": {"source_guid": "sg-001"}}

        ctx, ident = _make_context_and_identity(
            service=service, manager=manager, file_name="test_file"
        )

        with patch("agent_actions.llm.batch.services.processing_recovery.fire_event"):
            finalize_batch_output(
                ctx,
                ident,
                batch_results=[_make_result("id-1")],
                context_map=context_map,
            )

        service._write_filtered_dispositions.assert_called_once_with(context_map, "test_action")

    def test_finalize_uses_service_action_name_when_action_name_none(self):
        """When action_name=None, _write_filtered_dispositions still uses service._workflow_name.

        Mirrors how _clear_deferred_dispositions and _update_prompt_trace_responses
        fall back to effective_action_name. A None action_name must not silently
        skip filtered-disposition writes — the service knows its own name.
        """
        service = _mock_service()
        service._workflow_name = "fallback_action"
        manager = MagicMock()
        context_map = {"custom-filtered-1": {"source_guid": "sg-001"}}

        ctx, ident = _make_context_and_identity(
            service=service, manager=manager, action_name=None, file_name="test_file"
        )

        with patch("agent_actions.llm.batch.services.processing_recovery.fire_event"):
            finalize_batch_output(
                ctx,
                ident,
                batch_results=[_make_result("id-1")],
                context_map=context_map,
            )

        service._write_filtered_dispositions.assert_called_once_with(context_map, "fallback_action")


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

        ctx, ident = _make_context_and_identity(service=service, file_name="test_file")

        with patch(
            "agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager"
        ) as mock_mgr:
            handle_retry_recovery(
                ctx,
                ident,
                state=state,
                recovery_results=[],
                accumulated=[],
                context_map={},
            )

        assert state.retry_attempt == 2
        mock_mgr.save.assert_called_once()


# ---------------------------------------------------------------------------
# TestApplyExhaustedReprompt (direct unit tests for exhaustion.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TestStampBatchRecords (direct unit tests)
# ---------------------------------------------------------------------------


class TestRemoveBatchPlaceholder:
    """Direct tests for _remove_batch_placeholder."""

    def test_removes_valid_placeholder(self, tmp_path):
        import json

        from agent_actions.llm.batch.services.processing_recovery import (
            _remove_batch_placeholder,
        )

        placeholder = tmp_path / "output.json"
        placeholder.write_text(
            json.dumps({"batch_job_id": "batch_123", "status": "submitted", "agent": "test"})
        )

        _remove_batch_placeholder(placeholder)

        assert not placeholder.exists()

    def test_leaves_non_placeholder_json(self, tmp_path):
        import json

        from agent_actions.llm.batch.services.processing_recovery import (
            _remove_batch_placeholder,
        )

        real_output = tmp_path / "output.json"
        real_output.write_text(json.dumps([{"content": {"data": "real"}}]))

        _remove_batch_placeholder(real_output)

        assert real_output.exists()  # NOT deleted

    def test_leaves_completed_batch_file(self, tmp_path):
        import json

        from agent_actions.llm.batch.services.processing_recovery import (
            _remove_batch_placeholder,
        )

        completed = tmp_path / "output.json"
        completed.write_text(
            json.dumps({"batch_job_id": "batch_123", "status": "completed", "agent": "test"})
        )

        _remove_batch_placeholder(completed)

        assert completed.exists()  # status != submitted, not removed

    def test_handles_missing_file(self, tmp_path):
        from agent_actions.llm.batch.services.processing_recovery import (
            _remove_batch_placeholder,
        )

        missing = tmp_path / "nonexistent.json"
        _remove_batch_placeholder(missing)  # no error

    def test_handles_malformed_json(self, tmp_path):
        from agent_actions.llm.batch.services.processing_recovery import (
            _remove_batch_placeholder,
        )

        bad_file = tmp_path / "corrupt.json"
        bad_file.write_text("not json{{{")

        _remove_batch_placeholder(bad_file)

        assert bad_file.exists()  # not deleted, just warned


def _make_parent_entry(
    batch_id: str = "batch-parent",
    file_name: str = "my_action",
    record_count: int = 10,
    status: str = BatchStatus.COMPLETED,
) -> BatchJobEntry:
    return BatchJobEntry(
        batch_id=batch_id,
        status=status,
        timestamp="2026-05-01T00:00:00Z",
        provider="openai",
        record_count=record_count,
        file_name=file_name,
    )


def _make_eval_loop_mocks(max_attempts: int = 2, on_exhausted: str = "return_last"):
    loop = MagicMock()
    strategy = MagicMock()
    strategy.name = "validation"
    strategy.max_attempts = max_attempts
    strategy.on_exhausted = on_exhausted
    return loop, strategy


class TestRecoveryLoopRootCauses:
    """Recovery entries consumed + RecoveryState loaded from disk."""

    def test_completed_recovery_entry_is_processed(self):
        parent_entry = _make_parent_entry()
        recovery_entry = _make_entry(
            recovery_type="repair",
            batch_id="batch-recovery",
            parent_file_name="my_action",
            status=BatchStatus.COMPLETED,
        )

        manager = MagicMock()
        manager.get_all_jobs.return_value = {
            "my_action": parent_entry,
            "my_action_repair_1": recovery_entry,
        }

        svc = BatchProcessingService.__new__(BatchProcessingService)
        svc._registry_manager_factory = MagicMock(return_value=manager)
        svc._workflow_name = "test_action"
        svc._is_batch_ready_for_processing = MagicMock(return_value=True)

        calls_received = []
        svc._process_single_batch_file = MagicMock(
            side_effect=lambda **kwargs: calls_received.append(kwargs["file_name"])
            or "/tmp/output.json"
        )

        svc.process_all_batch_results("/tmp/output", action_name="test_action")

        assert "my_action_repair_1" in calls_received


class TestDownstreamBugs:
    """Cancelled status, RuntimeError propagation, state mutation, None-content filter."""

    def test_completed_plus_cancelled_returns_completed(self):
        stats = BatchRegistryStats(total_jobs=2, completed=1, failed=0, in_progress=0, cancelled=1)
        assert stats.overall_status == "completed"

    def test_all_cancelled_returns_cancelled(self):
        stats = BatchRegistryStats(total_jobs=2, completed=0, failed=0, in_progress=0, cancelled=2)
        assert stats.overall_status == "cancelled"

    def test_on_exhausted_raise_propagates_through_process_all(self):
        svc = BatchProcessingService.__new__(BatchProcessingService)
        manager = MagicMock()

        manager.get_all_jobs.return_value = {"my_action": _make_parent_entry()}
        manager.get_registry_stats.return_value = BatchRegistryStats(
            total_jobs=1, completed=0, failed=1, in_progress=0, cancelled=0
        )

        svc._registry_manager_factory = MagicMock(return_value=manager)
        svc._workflow_name = "test_action"
        svc._is_batch_ready_for_processing = MagicMock(return_value=True)
        svc._process_single_batch_file = MagicMock(
            side_effect=RuntimeError("Reprompt validation exhausted")
        )

        with pytest.raises(RuntimeError, match="Reprompt validation exhausted"):
            svc.process_all_batch_results("/tmp/output", action_name="test_action")


# ---------------------------------------------------------------------------
# TestStaleRecoveryState — F13 regression tests
# ---------------------------------------------------------------------------


class TestStaleRecoveryState:
    """Stale recovery state from a crashed run must not poison subsequent runs.

    F13: If a batch run crashes after saving recovery_state but before
    completing, the next fresh run must NOT inherit the stale attempt counter.

    The primary regression test for stale state poisoning is
    TestRecoveryLoopRootCauses.test_process_original_batch_ignores_stale_recovery_state.
    This class covers the complementary cleanup concern: finalization deletes
    leftover state files.
    """

    @patch("agent_actions.llm.batch.services.processing._finalize_batch_output_impl")
    @patch("agent_actions.llm.batch.services.processing._cleanup_recovery_impl")
    @patch("agent_actions.llm.batch.services.processing.RecoveryStateManager")
    def test_finalize_deletes_stale_recovery_state(
        self, mock_state_mgr, mock_cleanup, mock_finalize
    ):
        """_finalize_batch_output must delete any recovery state file on disk.

        Ensures stale state from a crashed run is cleaned up after successful
        completion of the original batch path.
        """
        mock_finalize.return_value = "/tmp/output.json"

        svc = BatchProcessingService.__new__(BatchProcessingService)
        svc._storage_backend = MagicMock()
        svc._workflow_name = "test_action"

        ctx, ident = _make_context_and_identity(
            service=svc,
            output_directory="/tmp/output",
            file_name="my_action",
            batch_id="batch-123",
        )

        svc._finalize_batch_output(
            context=ctx,
            identity=ident,
            batch_results=[_make_result("id-1")],
            context_map={},
        )

        mock_state_mgr.delete.assert_called_once()
        assert mock_state_mgr.delete.call_args[0][2] == "my_action"
