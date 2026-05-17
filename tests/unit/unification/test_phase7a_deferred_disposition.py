"""Phase 7a: DEFERRED disposition must be stamped on batch submit.

U-3.3: After successful batch submission, every record sent to the provider
must have DISPOSITION_DEFERRED in the storage backend. Records that were
filtered/skipped during preparation must NOT receive DEFERRED.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.storage.backend import DISPOSITION_DEFERRED


def _make_submission_service(
    *,
    storage_backend: Any = None,
) -> BatchSubmissionService:
    """Build a BatchSubmissionService with mocked provider/registry."""
    preparator = BatchTaskPreparator(
        action_indices={},
        dependency_configs={},
        storage_backend=storage_backend,
    )

    client_resolver = MagicMock()
    mock_provider = MagicMock()
    mock_provider.prepare_tasks.side_effect = lambda tasks, config: tasks
    mock_provider.submit_batch.return_value = ("batch-123", "submitted")
    client_resolver.get_for_config.return_value = mock_provider

    context_manager = MagicMock()
    registry_manager_factory = MagicMock()

    return BatchSubmissionService(
        task_preparator=preparator,
        client_resolver=client_resolver,
        context_manager=context_manager,
        registry_manager_factory=registry_manager_factory,
        storage_backend=storage_backend,
    )


def _make_agent_config(**overrides) -> dict[str, Any]:
    base = {
        "action_name": "test_action",
        "agent_type": "llm",
        "model_vendor": "openai",
        "prompt": "Process: {{ content }}",
        "json_mode": False,
    }
    base.update(overrides)
    return base


class TestDeferredStampedOnSubmit:
    """U-3.3: DEFERRED must be stamped on batch submit."""

    def test_deferred_stamped_for_submitted_records(self):
        """After batch submit, DISPOSITION_DEFERRED exists for each submitted record."""
        backend = MagicMock()
        backend.set_disposition = MagicMock()

        service = _make_submission_service(storage_backend=backend)
        agent_config = _make_agent_config()

        records = [
            {"target_id": "t-001", "source_guid": "sg-001", "content": {"text": "record 1"}},
            {"target_id": "t-002", "source_guid": "sg-002", "content": {"text": "record 2"}},
        ]

        # Mock TaskPreparer to let all records through
        with patch(
            "agent_actions.llm.batch.processing.preparator.get_task_preparer"
        ) as mock_get_preparer:
            mock_preparer = MagicMock()
            prepared = MagicMock()
            prepared.guard_status = None  # no guard
            prepared.passthrough_fields = {}
            prepared.llm_context = {"text": "content"}
            prepared.formatted_prompt = "Process: content"
            prepared.source_guid = "sg-001"
            mock_preparer.prepare.return_value = prepared
            mock_get_preparer.return_value = mock_preparer

            result = service.submit_batch_job(agent_config, "test-batch", records)

        assert result.is_submitted

        # Verify DEFERRED was stamped for each submitted record
        deferred_calls = [
            call
            for call in backend.set_disposition.call_args_list
            if call.kwargs.get("disposition") == DISPOSITION_DEFERRED
            or (len(call.args) >= 3 and call.args[2] == DISPOSITION_DEFERRED)
        ]
        stamped_record_ids = set()
        for call in deferred_calls:
            if call.kwargs.get("record_id"):
                stamped_record_ids.add(call.kwargs["record_id"])
            elif len(call.args) >= 2:
                stamped_record_ids.add(call.args[1])

        assert "sg-001" in stamped_record_ids or "t-001" in stamped_record_ids, (
            f"DEFERRED not stamped for record t-001/sg-001. "
            f"All set_disposition calls: {backend.set_disposition.call_args_list}"
        )

    def test_no_deferred_without_storage_backend(self):
        """When no storage backend, submit succeeds without disposition writes."""
        service = _make_submission_service(storage_backend=None)
        agent_config = _make_agent_config()
        records = [
            {"target_id": "t-001", "source_guid": "sg-001", "content": {"text": "record 1"}},
        ]

        with patch(
            "agent_actions.llm.batch.processing.preparator.get_task_preparer"
        ) as mock_get_preparer:
            mock_preparer = MagicMock()
            prepared = MagicMock()
            prepared.guard_status = None
            prepared.passthrough_fields = {}
            prepared.llm_context = {"text": "content"}
            prepared.formatted_prompt = "Process: content"
            prepared.source_guid = "sg-001"
            mock_preparer.prepare.return_value = prepared
            mock_get_preparer.return_value = mock_preparer

            result = service.submit_batch_job(agent_config, "test-batch", records)

        # Should succeed without crashing — no backend to write to
        assert result.is_submitted

    def test_deferred_includes_batch_id_detail(self):
        """DEFERRED disposition should include batch_job_id in reason/detail."""
        backend = MagicMock()
        backend.set_disposition = MagicMock()

        service = _make_submission_service(storage_backend=backend)
        agent_config = _make_agent_config()
        records = [
            {"target_id": "t-001", "source_guid": "sg-001", "content": {"text": "record 1"}},
        ]

        with patch(
            "agent_actions.llm.batch.processing.preparator.get_task_preparer"
        ) as mock_get_preparer:
            mock_preparer = MagicMock()
            prepared = MagicMock()
            prepared.guard_status = None
            prepared.passthrough_fields = {}
            prepared.llm_context = {"text": "content"}
            prepared.formatted_prompt = "Process: content"
            prepared.source_guid = "sg-001"
            mock_preparer.prepare.return_value = prepared
            mock_get_preparer.return_value = mock_preparer

            service.submit_batch_job(agent_config, "test-batch", records)

        # Find the DEFERRED call and verify it references the batch_id
        deferred_calls = [
            call
            for call in backend.set_disposition.call_args_list
            if call.kwargs.get("disposition") == DISPOSITION_DEFERRED
            or (len(call.args) >= 3 and call.args[2] == DISPOSITION_DEFERRED)
        ]
        assert len(deferred_calls) > 0, "No DEFERRED disposition written"
        call = deferred_calls[0]
        reason = call.kwargs.get("reason", "")
        assert "batch-123" in reason, f"batch_id not in DEFERRED reason: {reason}"

    def test_skipped_and_filtered_records_not_stamped(self):
        """Records that were skipped/filtered during prep must NOT receive DEFERRED."""
        backend = MagicMock()
        service = _make_submission_service(storage_backend=backend)

        # Hand-craft a context_map with mixed filter statuses
        context_map: dict[str, Any] = {}

        included_entry = {"source_guid": "sg-included", "content": {"text": "ok"}}
        BatchContextMetadata.set_filter_status(included_entry, FilterStatus.INCLUDED)
        context_map["t-included"] = included_entry

        skipped_entry = {"source_guid": "sg-skipped", "content": {"text": "skip"}}
        BatchContextMetadata.set_filter_status(skipped_entry, FilterStatus.SKIPPED)
        context_map["t-skipped"] = skipped_entry

        filtered_entry = {"source_guid": "sg-filtered", "content": {"text": "filter"}}
        BatchContextMetadata.set_filter_status(filtered_entry, FilterStatus.FILTERED)
        context_map["t-filtered"] = filtered_entry

        failed_entry = {"source_guid": "sg-failed", "content": {"text": "fail"}}
        BatchContextMetadata.set_filter_status(failed_entry, FilterStatus.FAILED)
        context_map["t-failed"] = failed_entry

        # Call _stamp_deferred directly
        service._stamp_deferred(context_map, "test_action", "batch-999")

        # Only the INCLUDED record should have been stamped
        assert backend.set_disposition.call_count == 1
        call = backend.set_disposition.call_args
        assert call.args[1] == "sg-included"
        assert call.args[2] == DISPOSITION_DEFERRED
