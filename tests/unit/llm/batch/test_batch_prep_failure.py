"""Tests for batch preparator handling of per-record prep failures.

When prompt preparation fails for a record (TemplateVariableError,
RecordContextError), the record must be stamped FAILED in the context_map
and written as a disposition, not silently dropped.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.services.collect import collect_batch_rows
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.record.state import RecordState
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


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


class TestThePreparationErrorIsKeptForCollection:
    """The record is collected from the context map, in this process when nothing was
    sent and in a later one when something was. Read off its history, the error is gone
    where preparation could not move the record to failed, and cut to 200 characters."""

    ERROR = "Template for 'my_action' references undefined variables: topic"

    @staticmethod
    def _failed(error: Exception, state: str = "active") -> dict[str, Any]:
        row = {"target_id": "t1", "source_guid": "g1", "content": {}}
        context_map = {"t1": {**row, "_state": state}}
        BatchTaskPreparator._mark_prep_failed(row, context_map, "my_action", error)
        return context_map

    def test_the_error_is_kept_on_the_entry(self):
        entry = self._failed(ValueError(self.ERROR))["t1"]

        assert entry["_batch_prep_error"] == self.ERROR

    def test_it_is_kept_where_the_entry_cannot_move_to_failed(self):
        entry = self._failed(ValueError(self.ERROR), state="processed")["t1"]

        assert entry["_batch_prep_error"] == self.ERROR

    def test_it_is_kept_at_the_length_its_disposition_takes(self):
        entry = self._failed(ValueError("x" * 600))["t1"]

        assert entry["_batch_prep_error"] == "x" * 500

    def test_a_tool_is_never_handed_it(self):
        entry = self._failed(ValueError(self.ERROR))["t1"]

        assert "_batch_prep_error" in entry
        assert "_batch_prep_error" not in BatchContextMetadata.strip_internal_fields(entry)

    def test_a_record_collected_from_the_saved_map_fails_with_its_error(self, tmp_path):
        from agent_actions.llm.batch.infrastructure.context import BatchContextManager
        from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
        from agent_actions.processing.types import ProcessingStatus
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
        backend.initialize()
        BatchContextManager.save_batch_context_map(
            backend, "my_action", self._failed(ValueError(self.ERROR)), "page.json"
        )
        saved = BatchContextManager.load_batch_context_map(backend, "my_action", "page.json")

        (result,) = BatchResultStrategy().process(
            [], saved, agent_config={"action_name": "my_action"}
        )

        assert (result.status, result.error) == (ProcessingStatus.FAILED, self.ERROR)
        assert result.data[0]["_tombstone_reason"] == "prep_failed"

    def test_a_map_saved_without_it_fails_the_record_as_unprepared(self):
        from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy

        saved = {"t1": {"source_guid": "g1", "content": {}, "_batch_filter_status": "failed"}}

        (result,) = BatchResultStrategy().process(
            [], saved, agent_config={"action_name": "my_action"}
        )

        assert result.error == "prep_failed"


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


class TestEachEntryIsCollectedAsWhatPreparationFoundIt:
    """Built alike, a failed or upstream-blocked record is stored as a guard skip: the
    output says the guard turned away a record it passed, or one it never judged, and the
    action below takes it as input."""

    @staticmethod
    def _rows(context_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
        rows, _stats, _halt = collect_batch_rows(
            None, "my_action", {}, context_map, [], output_directory="/tmp/out"
        )
        return {row["source_guid"]: row for row in rows}

    def test_a_preparation_failure_is_a_failed_row_holding_its_error(self):
        row = {"target_id": "t1", "source_guid": "sg_failed", "content": {}}
        context_map = {"t1": {**row, "_state": "active"}}
        BatchTaskPreparator._mark_prep_failed(
            row, context_map, "my_action", ValueError("references undefined variables: topic")
        )

        held = self._rows(context_map)["sg_failed"]

        assert held["_state"] == "failed"
        assert held["_tombstone_reason"] == "prep_failed"
        assert held["metadata"]["reason"] == "prep_failed"
        assert {entry["reason"] for entry in held["_state_history"]} == {
            "references undefined variables: topic"
        }
        assert [key for key in held["metadata"] if key.startswith("skipped_by")] == []

    def test_a_record_blocked_upstream_is_a_cascade_skip(self):
        entry = {
            "source_guid": "sg_blocked",
            "content": {},
            "_batch_filter_status": "skipped",
            "_batch_skip_reason": "upstream_unprocessed",
        }

        row = self._rows({"t1": entry})["sg_blocked"]

        assert row["_state"] == "cascade_skipped"
        assert row["_tombstone_reason"] == "upstream_unprocessed"
        assert [key for key in row["metadata"] if key.startswith("skipped_by")] == []

    def test_a_guard_skip_says_why_and_carries_no_legacy_flag(self):
        entry = {
            "source_guid": "sg_skipped",
            "content": {},
            "_batch_filter_status": "skipped",
            "_batch_skip_reason": "guard_skip",
        }

        row = self._rows({"t1": entry})["sg_skipped"]

        assert row["_state"] == "guard_skipped"
        assert row["_tombstone_reason"] == "guard_skip"
        assert row["metadata"]["reason"] == "guard_skip"
        assert [key for key in row["metadata"] if key.startswith("skipped_by")] == []

    def test_an_entry_the_guard_filtered_gets_no_row(self):
        rows = self._rows(
            {"t1": {"source_guid": "gone", "content": {}, "_batch_filter_status": "filtered"}}
        )

        assert rows == {}


class TestEveryRecordFailingPreparation:
    """Nothing is sent, and the run writes each failure itself."""

    ROW = {"target_id": "t1", "source_guid": "sg_001", "content": {}}

    def _service(self, tmp_path) -> tuple[BatchSubmissionService, SQLiteBackend]:
        backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
        backend.initialize()
        row = dict(self.ROW)
        context_map = {"t1": {**row, "_state": "active"}}
        BatchTaskPreparator._mark_prep_failed(
            row, context_map, "my_action", ValueError("references undefined variables: topic")
        )
        registry = MagicMock()
        registry.get_batch_job.return_value = None
        service = BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            registry_manager_factory=lambda name: registry,
            storage_backend=backend,
        )
        service.prepare_batch_tasks = MagicMock(return_value=([], context_map))
        return service, backend

    def test_the_file_holds_each_failure_and_each_is_recorded_with_its_error(self, tmp_path):
        service, backend = self._service(tmp_path)

        result = service.submit_batch_job(
            agent_config={"action_name": "my_action"},
            batch_name="sub/page.csv",
            data=[dict(self.ROW)],
            output_directory=str(tmp_path / "out" / "sub"),
        )

        assert (result.batch_id, result.passthrough) == (None, {"type": "written"})
        assert backend.list_target_files("my_action") == ["sub/page.json"]
        (held,) = backend.read_target_for_rewrite("my_action", "sub/page.json")
        assert (held["source_guid"], held["_state"]) == ("sg_001", RecordState.FAILED.value)
        (failed,) = backend.get_disposition("my_action", disposition="failed")
        assert (failed["record_id"], failed["reason"], failed["detail"]) == (
            "sg_001",
            "references undefined variables: topic",
            "references undefined variables: topic",
        )

    def test_a_run_with_nowhere_to_write_is_refused_before_anything_is_recorded(self, tmp_path):
        service, backend = self._service(tmp_path)

        with pytest.raises(ConfigurationError, match="output_directory is required"):
            service.submit_batch_job(
                agent_config={"action_name": "my_action"},
                batch_name="page.csv",
                data=[dict(self.ROW)],
                output_directory=None,
            )

        assert backend.list_target_files("my_action") == []
        assert backend.get_disposition("my_action", disposition="failed") == []
