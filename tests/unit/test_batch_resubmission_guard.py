"""Tests for batch resubmission prevention when a completed batch is still to collect."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services.submission import BatchSubmissionService


def _make_service(force_batch: bool = False, storage_backend=None) -> BatchSubmissionService:
    """Create a BatchSubmissionService with mocked dependencies."""
    return BatchSubmissionService(
        task_preparator=MagicMock(),
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        registry_manager_factory=MagicMock(),
        force_batch=force_batch,
        storage_backend=storage_backend,
    )


def _make_entry(status: str, batch_id: str = "batch-123") -> BatchJobEntry:
    """Create a BatchJobEntry with given status."""
    return BatchJobEntry(
        batch_id=batch_id,
        status=status,
        timestamp="2026-04-19T00:00:00+00:00",
        provider="openai",
        record_count=10,
    )


def _stub_submission_path(svc: BatchSubmissionService, batch_id: str = "batch-new") -> None:
    """Wire up mocks so submit_batch_job can reach _submit_to_provider."""
    mock_prepared = MagicMock()
    mock_prepared.tasks = [{"target_id": "r1", "content": "x", "prompt": "p"}]
    mock_prepared.context_map = {}
    mock_prepared.task_count = 1
    mock_prepared.stats = MagicMock(total_filtered=0, total_skipped=0)
    svc._task_preparator.prepare_tasks.return_value = mock_prepared

    svc._client_resolver.get_for_config.return_value = MagicMock(
        submit_batch=MagicMock(return_value=(batch_id, "submitted"))
    )


class TestCompletedBatchSkipsResubmission:
    """A completed batch whose results are not collected yet must block new submission."""

    def test_completed_batch_returns_existing_batch_id(self, tmp_path):
        """When a completed batch exists, submit_batch_job returns its ID without resubmitting."""
        svc = _make_service()
        entry = _make_entry(BatchStatus.COMPLETED, batch_id="batch-done-1")
        svc._registry_manager_factory.return_value.get_batch_job.return_value = entry

        result = svc.submit_batch_job(
            agent_config={"model_vendor": "openai"},
            batch_name="my_action",
            data=[{"id": 1}],
            output_directory=str(tmp_path),
        )

        assert result.batch_id == "batch-done-1"
        assert result.is_submitted
        svc._task_preparator.prepare_tasks.assert_not_called()

    def test_completed_batch_does_not_compare_record_counts(self, tmp_path):
        """Completed batch blocks resubmission regardless of input data size change."""
        svc = _make_service()
        entry = _make_entry(BatchStatus.COMPLETED, batch_id="batch-5")
        entry.record_count = 5
        svc._registry_manager_factory.return_value.get_batch_job.return_value = entry

        result = svc.submit_batch_job(
            agent_config={"model_vendor": "openai"},
            batch_name="my_action",
            data=[{"id": i} for i in range(10)],
            output_directory=str(tmp_path),
        )

        assert result.batch_id == "batch-5"
        svc._task_preparator.prepare_tasks.assert_not_called()


class TestACollectedBatchNoLongerBlocks:
    """Its results are written, so it is no reason to skip an action that has to run."""

    def test_a_collected_batch_allows_new_submission(self, tmp_path):
        svc = _make_service()
        entry = _make_entry(BatchStatus.COMPLETED, batch_id="batch-spent")
        entry.collected_at = "2026-04-19T01:00:00+00:00"
        svc._registry_manager_factory.return_value.get_batch_job.return_value = entry
        _stub_submission_path(svc, batch_id="batch-new")

        with (
            patch("agent_actions.llm.batch.services.submission.fire_event"),
            patch("agent_actions.llm.batch.services.submission.get_manager"),
        ):
            result = svc.submit_batch_job(
                agent_config={"model_vendor": "openai"},
                batch_name="my_action",
                data=[{"id": 1}],
                output_directory=str(tmp_path),
            )

        assert result.batch_id == "batch-new"
        svc._task_preparator.prepare_tasks.assert_called_once()


class TestInFlightBatchStillBlocks:
    """Existing in-flight guard must continue to work."""

    @pytest.mark.parametrize(
        "status", sorted(BatchStatus.in_flight_states(), key=lambda s: s.value)
    )
    def test_in_flight_statuses_block_resubmission(self, tmp_path, status):
        """All in-flight statuses block new submission."""
        svc = _make_service()
        entry = _make_entry(status, batch_id="batch-inflight")
        svc._registry_manager_factory.return_value.get_batch_job.return_value = entry

        result = svc.submit_batch_job(
            agent_config={"model_vendor": "openai"},
            batch_name="my_action",
            data=[{"id": 1}],
            output_directory=str(tmp_path),
        )

        assert result.batch_id == "batch-inflight"
        svc._task_preparator.prepare_tasks.assert_not_called()

    @pytest.mark.parametrize(
        "status",
        [
            *sorted(BatchStatus.in_flight_states(), key=lambda s: s.value),
            BatchStatus.COMPLETED,
        ],
    )
    def test_a_job_still_owed_blocks_when_the_input_is_now_empty(self, tmp_path, status):
        """Its results are owed for this file. Stored empty and reported written
        instead, the file would read done while its job is still out."""
        svc = _make_service(storage_backend=MagicMock())
        entry = _make_entry(status, batch_id="batch-owed")
        svc._registry_manager_factory.return_value.get_batch_job.return_value = entry

        result = svc.submit_batch_job(
            agent_config={"model_vendor": "openai"},
            batch_name="my_action",
            data=[],
            output_directory=str(tmp_path),
            run_inputs=[],
        )

        assert result.batch_id == "batch-owed"
        assert result.passthrough is None


class TestFailedCancelledBatchAllowsResubmission:
    """Failed and cancelled batches should allow automatic resubmission."""

    @pytest.mark.parametrize("status", [BatchStatus.FAILED, BatchStatus.CANCELLED])
    def test_failed_or_cancelled_batch_allows_new_submission(self, tmp_path, status):
        """Failed/cancelled batches do not block — framework should retry."""
        svc = _make_service()
        entry = _make_entry(status, batch_id="batch-failed")
        svc._registry_manager_factory.return_value.get_batch_job.return_value = entry
        _stub_submission_path(svc, batch_id="batch-new")

        with (
            patch("agent_actions.llm.batch.services.submission.fire_event"),
            patch("agent_actions.llm.batch.services.submission.get_manager"),
        ):
            result = svc.submit_batch_job(
                agent_config={"model_vendor": "openai"},
                batch_name="my_action",
                data=[{"id": 1}],
                output_directory=str(tmp_path),
            )

        assert result.batch_id == "batch-new"
        svc._task_preparator.prepare_tasks.assert_called_once()


class TestForceOverridesCompletedGuard:
    """Force flag must bypass the completed batch guard."""

    def test_force_flag_resubmits_over_completed_batch(self, tmp_path):
        """submit_batch_job(force=True) submits new batch even when completed exists."""
        svc = _make_service()
        entry = _make_entry(BatchStatus.COMPLETED, batch_id="batch-done")
        svc._registry_manager_factory.return_value.get_batch_job.return_value = entry
        _stub_submission_path(svc, batch_id="batch-forced")

        with (
            patch("agent_actions.llm.batch.services.submission.fire_event"),
            patch("agent_actions.llm.batch.services.submission.get_manager"),
        ):
            result = svc.submit_batch_job(
                agent_config={"model_vendor": "openai"},
                batch_name="my_action",
                data=[{"id": 1}],
                output_directory=str(tmp_path),
                force=True,
            )

        assert result.batch_id == "batch-forced"
        svc._task_preparator.prepare_tasks.assert_called_once()

    def test_force_batch_constructor_flag_resubmits_over_completed(self, tmp_path):
        """BatchSubmissionService(force_batch=True) bypasses completed guard."""
        svc = _make_service(force_batch=True)
        entry = _make_entry(BatchStatus.COMPLETED, batch_id="batch-done")
        svc._registry_manager_factory.return_value.get_batch_job.return_value = entry
        _stub_submission_path(svc, batch_id="batch-forced-2")

        with (
            patch("agent_actions.llm.batch.services.submission.fire_event"),
            patch("agent_actions.llm.batch.services.submission.get_manager"),
        ):
            result = svc.submit_batch_job(
                agent_config={"model_vendor": "openai"},
                batch_name="my_action",
                data=[{"id": 1}],
                output_directory=str(tmp_path),
            )

        assert result.batch_id == "batch-forced-2"


class TestNoBatchEntryAllowsSubmission:
    """When no batch exists in registry, normal submission proceeds."""

    def test_no_existing_entry_submits_normally(self, tmp_path):
        """First-time batch submission works when registry is empty."""
        svc = _make_service()
        svc._registry_manager_factory.return_value.get_batch_job.return_value = None
        _stub_submission_path(svc, batch_id="batch-first")

        with (
            patch("agent_actions.llm.batch.services.submission.fire_event"),
            patch("agent_actions.llm.batch.services.submission.get_manager"),
        ):
            result = svc.submit_batch_job(
                agent_config={"model_vendor": "openai"},
                batch_name="my_action",
                data=[{"id": 1}],
                output_directory=str(tmp_path),
            )

        assert result.batch_id == "batch-first"
        svc._task_preparator.prepare_tasks.assert_called_once()
