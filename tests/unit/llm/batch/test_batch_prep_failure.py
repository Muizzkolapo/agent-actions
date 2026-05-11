"""Tests for batch preparator handling of per-record prep failures.

When prompt preparation fails for a record (TemplateVariableError,
RecordContextError), the record must be stamped FAILED in the context_map
and written as a disposition, not silently dropped.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.batch_passthrough_builder import (
    BatchPassthroughBuilder,
)
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.record.state import RecordState


def _make_preparator(**kwargs: Any) -> BatchTaskPreparator:
    return BatchTaskPreparator(
        action_indices=kwargs.get("action_indices", {}),
        dependency_configs=kwargs.get("dependency_configs", {}),
        storage_backend=kwargs.get("storage_backend"),
        version_context=kwargs.get("version_context"),
    )


class TestMarkPrepFailed:
    """_mark_prep_failed stamps context_map entry with FilterStatus.FAILED and _state."""

    def test_stamps_filter_status_and_state(self):
        row = {"target_id": "tid_001", "source_guid": "sg_001"}
        context_map = {"tid_001": row.copy()}
        context_map["tid_001"]["_batch_filter_status"] = "included"

        BatchTaskPreparator._mark_prep_failed(
            row, context_map, "test_action", ValueError("missing field")
        )

        entry = context_map["tid_001"]
        assert BatchContextMetadata.get_filter_status(entry) == FilterStatus.FAILED
        assert entry["_state"] == RecordState.FAILED.value
        assert len(entry["_state_history"]) == 1
        assert entry["_state_history"][0]["reason"].startswith("missing field")

    def test_no_target_id_is_noop(self):
        """If row has no target_id, _mark_prep_failed is a no-op."""
        row = {"source_guid": "sg_001"}
        context_map = {}

        # Should not raise
        BatchTaskPreparator._mark_prep_failed(row, context_map, "test_action", ValueError("boom"))

    def test_target_id_not_in_context_map_is_noop(self):
        """If target_id exists but isn't in context_map, _mark_prep_failed is a no-op."""
        row = {"target_id": "tid_orphan"}
        context_map = {}

        BatchTaskPreparator._mark_prep_failed(row, context_map, "test_action", ValueError("boom"))


class TestBatchPreparatorCatchBlock:
    """Integration test: prep failure flows through the full prepare_tasks loop."""

    @patch("agent_actions.llm.batch.processing.preparator.get_task_preparer")
    @patch("agent_actions.prompt.formatter.PromptFormatter.get_raw_prompt", return_value="prompt")
    @patch.object(BatchTaskPreparator, "_run_preflight_validation")
    def test_failed_record_in_context_map(self, _mock_preflight, _mock_prompt, mock_get_preparer):
        """Record that fails prep is stamped FAILED in context_map, not dropped."""
        mock_preparer = MagicMock()
        mock_preparer.prepare.side_effect = ValueError("Template rendering failed")
        mock_get_preparer.return_value = mock_preparer

        mock_provider = MagicMock()
        mock_provider.prepare_tasks.return_value = []

        preparator = _make_preparator()
        result = preparator.prepare_tasks(
            agent_config={
                "agent_type": "test",
                "action_name": "test_action",
                "model_vendor": "openai",
                "model_name": "gpt-4",
                "json_mode": False,
            },
            data=[{"target_id": "tid_001", "source_guid": "sg_001", "content": {}}],
            provider=mock_provider,
            output_directory="/tmp/test",
        )

        assert "tid_001" in result.context_map
        entry = result.context_map["tid_001"]
        assert BatchContextMetadata.get_filter_status(entry) == FilterStatus.FAILED
        assert entry["_state"] == RecordState.FAILED.value
        assert result.stats.error_items == 1

    @patch("agent_actions.llm.batch.processing.preparator.get_task_preparer")
    @patch("agent_actions.prompt.formatter.PromptFormatter.get_raw_prompt", return_value="prompt")
    @patch.object(BatchTaskPreparator, "_run_preflight_validation")
    def test_disposition_written_on_failure(self, _mock_preflight, _mock_prompt, mock_get_preparer):
        """When storage_backend is available, DISPOSITION_FAILED is written."""
        mock_preparer = MagicMock()
        mock_preparer.prepare.side_effect = ValueError("boom")
        mock_get_preparer.return_value = mock_preparer

        mock_backend = MagicMock()
        mock_provider = MagicMock()
        mock_provider.prepare_tasks.return_value = []

        preparator = _make_preparator(storage_backend=mock_backend)
        preparator.prepare_tasks(
            agent_config={
                "agent_type": "test",
                "action_name": "test_action",
                "model_vendor": "openai",
                "model_name": "gpt-4",
                "json_mode": False,
            },
            data=[{"target_id": "tid_001", "source_guid": "sg_001", "content": {}}],
            provider=mock_provider,
            output_directory="/tmp/test",
        )

        mock_backend.set_disposition.assert_called_once()
        call_kwargs = mock_backend.set_disposition.call_args
        assert call_kwargs[0][2] == "failed"  # disposition arg


class TestPassthroughBuilderIncludesFailed:
    """BatchPassthroughBuilder.from_context includes FAILED entries."""

    def test_failed_entries_included_in_passthrough(self):
        context_map = {
            "tid_001": {
                "source_guid": "sg_001",
                "content": {},
                "_batch_filter_status": "failed",
            },
            "tid_002": {
                "source_guid": "sg_002",
                "content": {},
                "_batch_filter_status": "included",
            },
        }

        builder = BatchPassthroughBuilder(output_directory="/tmp/test/my_action")
        result = builder.from_context(context_map, reason="prep_failed")

        assert len(result["data"]) == 1
        assert result["data"][0]["source_guid"] == "sg_001"


class TestHandleEmptyTasksPrepFailed:
    """_handle_empty_tasks returns passthrough when all records failed prep."""

    def test_all_records_failed_returns_passthrough(self):
        service = BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(),
        )

        context_map = {
            "tid_001": {
                "source_guid": "sg_001",
                "_batch_filter_status": "failed",
            },
        }

        result = service._handle_empty_tasks(
            agent_config={},
            context_map=context_map,
            data=[{"id": 1}],
            output_directory="/tmp/out",
        )

        assert result.passthrough is not None
        assert result.passthrough["type"] == "tombstone"
