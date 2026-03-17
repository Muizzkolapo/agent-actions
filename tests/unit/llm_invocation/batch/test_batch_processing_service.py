"""Tests for BatchProcessingService.

TDD: These tests are written BEFORE the implementation to define
the expected behavior of the processing service.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestBatchProcessingServiceInit:
    """Tests for BatchProcessingService initialization."""

    def test_init_with_all_dependencies(self):
        """Should initialize with all required dependencies."""
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        client_resolver = MagicMock()
        context_manager = MagicMock()
        result_processor = MagicMock()
        registry_manager_factory = MagicMock()

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            result_processor=result_processor,
            registry_manager_factory=registry_manager_factory,
        )

        assert service._client_resolver is client_resolver
        assert service._context_manager is context_manager
        assert service._result_processor is result_processor

    def test_init_with_optional_source_handler(self):
        """Should accept optional source handler."""
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        source_handler = MagicMock()

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
            source_handler=source_handler,
        )

        assert service._source_handler is source_handler


class TestIsBatchReadyForProcessing:
    """Tests for _is_batch_ready_for_processing helper method."""

    def test_returns_true_when_completed(self):
        """Should return True when batch status is completed."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        manager = MagicMock()

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        result = service._is_batch_ready_for_processing("batch_123", "/tmp/output")

        assert result is True

    def test_returns_false_when_in_progress(self):
        """Should return False when batch is still in progress."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.IN_PROGRESS

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        manager = MagicMock()

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        result = service._is_batch_ready_for_processing("batch_123", "/tmp/output")

        assert result is False

    def test_returns_false_on_exception(self):
        """Should return False when status check fails."""
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.side_effect = Exception("API error")

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
        )

        result = service._is_batch_ready_for_processing("batch_123", "/tmp/output")

        assert result is False


class TestDetermineOutputPath:
    """Tests for _determine_output_path helper method."""

    def test_uses_file_name_when_provided(self, tmp_path):
        """Should use file_name stem for output path."""
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
        )

        result = service._determine_output_path(
            output_directory=str(tmp_path),
            file_name="my_batch_file.jsonl",
            batch_id="batch_123",
        )

        assert result == tmp_path / "my_batch_file.json"

    def test_uses_batch_id_when_no_file_name(self, tmp_path):
        """Should use batch_id for output path when file_name is None."""
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
        )

        result = service._determine_output_path(
            output_directory=str(tmp_path),
            file_name=None,
            batch_id="batch_123",
        )

        assert result == tmp_path / "batch_123_processed_output.json"


class TestWriteBatchOutput:
    """Tests for _write_batch_output helper method."""

    def test_writes_main_output_file(self, tmp_path):
        """Should write main output to storage backend."""
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        # Create mock storage backend that tracks writes
        mock_storage = MagicMock()
        written_data = []

        def capture_write(action_name, relative_path, data):
            written_data.append({"action_name": action_name, "path": relative_path, "data": data})

        mock_storage.write_target = capture_write

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
            storage_backend=mock_storage,
            action_name="test_node",
        )

        main_output = [{"id": "1", "result": "success"}]
        output_file = tmp_path / "output.json"

        service._write_batch_output(
            output_file=output_file,
            main_output=main_output,
            output_directory=str(tmp_path),
        )

        # Verify storage backend was called with correct data
        assert len(written_data) == 1
        assert written_data[0]["action_name"] == "test_node"
        assert written_data[0]["path"] == "output.json"
        assert written_data[0]["data"] == main_output


class TestApplyWorkflowSessionId:
    """Tests for _apply_workflow_session_id helper method."""

    def test_restores_context_when_agent_config_missing(self):
        """Should restore workflow context from entry when agent_config is None."""
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        entry = BatchJobEntry(
            batch_id="batch-123",
            status="completed",
            timestamp="2024-01-01",
            provider="openai",
            workflow_session_id="session-123",
            is_versioned_agent=True,
            version_base_name="extract_qa",
        )

        result = BatchProcessingService._apply_workflow_session_id(None, entry)

        assert result == {
            "workflow_session_id": "session-123",
            "is_versioned_agent": True,
            "version_base_name": "extract_qa",
        }

    def test_returns_agent_config_when_entry_missing(self):
        """Should return agent_config when entry is None."""
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        agent_config = {"workflow_session_id": "session-123", "other": "config"}

        result = BatchProcessingService._apply_workflow_session_id(agent_config, None)

        assert result is agent_config

    def test_preserves_agent_config_when_entry_has_no_values(self):
        """Should preserve agent_config values when entry has no workflow context."""
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        entry = BatchJobEntry(
            batch_id="batch-123",
            status="completed",
            timestamp="2024-01-01",
            provider="openai",
            workflow_session_id=None,
        )
        agent_config = {"workflow_session_id": "session-123", "other": "config"}

        result = BatchProcessingService._apply_workflow_session_id(agent_config, entry)

        assert result == {"workflow_session_id": "session-123", "other": "config"}

    def test_preserves_entry_session_id(self):
        """Should overwrite agent_config session ID with entry session ID."""
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        entry = BatchJobEntry(
            batch_id="batch-123",
            status="completed",
            timestamp="2024-01-01",
            provider="openai",
            workflow_session_id="original-session-id",
        )
        agent_config = {"workflow_session_id": "different-session-id", "other": "config"}

        result = BatchProcessingService._apply_workflow_session_id(agent_config, entry)

        assert result["workflow_session_id"] == "original-session-id"
        assert result["other"] == "config"
        assert agent_config["workflow_session_id"] == "different-session-id"

    def test_merges_version_context_from_entry(self):
        """Should merge version context fields from entry into result."""
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        entry = BatchJobEntry(
            batch_id="batch-123",
            status="completed",
            timestamp="2024-01-01",
            provider="openai",
            workflow_session_id="session-123",
            is_versioned_agent=True,
            version_base_name="extract_qa",
        )
        agent_config = {"other": "config"}

        result = BatchProcessingService._apply_workflow_session_id(agent_config, entry)

        assert result["workflow_session_id"] == "session-123"
        assert result["is_versioned_agent"] is True
        assert result["version_base_name"] == "extract_qa"
        assert result["other"] == "config"


class TestProcessAllBatchResults:
    """Tests for process_all_batch_results method."""

    def test_raises_when_no_registry(self):
        """Should raise ProcessingError when no registry found."""
        from agent_actions.errors import ProcessingError
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        manager = MagicMock()
        manager.get_all_jobs.return_value = {}

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        with pytest.raises(ProcessingError) as exc_info:
            service.process_all_batch_results("/tmp/output")

        assert "No batch registry found" in str(exc_info.value)

    def test_skips_batches_not_completed(self, tmp_path):
        """Should skip batches that are not completed."""
        from agent_actions.errors import ProcessingError
        from agent_actions.llm.batch.core.batch_constants import BatchStatus
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        # Setup entry that is not completed
        entry = MagicMock()
        entry.batch_id = "batch_123"
        entry.status = BatchStatus.IN_PROGRESS
        entry.parent_file_name = None

        stats = MagicMock()
        stats.in_progress = 0

        manager = MagicMock()
        manager.get_all_jobs.return_value = {"file1.jsonl": entry}
        manager.get_registry_stats.return_value = stats

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.IN_PROGRESS

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        # Should raise because no files were processed
        with pytest.raises(ProcessingError) as exc_info:
            service.process_all_batch_results(str(tmp_path))

        assert "No batch results were successfully processed" in str(exc_info.value)

    def test_processes_completed_batches(self, tmp_path):
        """Should process completed batches and return file paths."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        # Setup completed entry
        entry = MagicMock()
        entry.batch_id = "batch_123"
        entry.record_count = 1
        entry.parent_file_name = None
        entry.recovery_type = None

        manager = MagicMock()
        manager.get_all_jobs.return_value = {"file1.jsonl": entry}

        # Provider returns completed status and results
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        result1 = MagicMock()
        result1.custom_id = "record_1"
        result1.content = {"answer": "test"}
        result1.success = True
        provider.retrieve_results.return_value = [result1]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {}

        result_processor = MagicMock()
        result_processor.process.return_value = [{"id": "1", "result": "done"}]

        # Create mock storage backend
        mock_storage = MagicMock()
        mock_storage.write_target = MagicMock()

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            result_processor=result_processor,
            registry_manager_factory=MagicMock(return_value=manager),
            storage_backend=mock_storage,
            action_name="test_node",
        )

        result = service.process_all_batch_results(str(tmp_path))

        assert len(result) == 1
        assert "file1.json" in result[0]


class TestProcessBatchResults:
    """Tests for process_batch_results method."""

    def test_raises_when_not_completed(self):
        """Should raise ProcessingError when batch not completed."""
        from agent_actions.errors import ProcessingError
        from agent_actions.llm.batch.core.batch_constants import BatchStatus
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.IN_PROGRESS

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        manager = MagicMock()

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        with pytest.raises(ProcessingError) as exc_info:
            service.process_batch_results(
                batch_id="batch_123",
                output_directory="/tmp/output",
                base_directory="/tmp/input",
                file_path="/tmp/input/data.jsonl",
            )

        assert "not completed" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Recovery-aware processing (#942)
# ---------------------------------------------------------------------------


class TestProcessAllBatchResultsSkipsRecoveryEntries:
    """Tests for recovery entry skipping in process_all_batch_results."""

    def test_skips_entries_with_parent_file_name(self, tmp_path):
        """Should skip recovery entries (parent_file_name is set)."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        # Original entry — completed
        original_entry = MagicMock(spec=BatchJobEntry)
        original_entry.batch_id = "batch_orig"
        original_entry.parent_file_name = None
        original_entry.recovery_type = None
        original_entry.record_count = 1

        # Recovery entry — should be skipped
        recovery_entry = MagicMock(spec=BatchJobEntry)
        recovery_entry.batch_id = "batch_retry_1"
        recovery_entry.parent_file_name = "original.json"
        recovery_entry.recovery_type = "retry"
        recovery_entry.record_count = 1

        manager = MagicMock()
        manager.get_all_jobs.return_value = {
            "original.json": original_entry,
            "original.json_retry_1": recovery_entry,
        }

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        provider.retrieve_results.return_value = [
            MagicMock(custom_id="a", content="ok", success=True)
        ]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {}

        result_processor = MagicMock()
        result_processor.process.return_value = [{"id": "1"}]

        mock_storage = MagicMock()
        mock_storage.write_target = MagicMock()

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            result_processor=result_processor,
            registry_manager_factory=MagicMock(return_value=manager),
            storage_backend=mock_storage,
            action_name="test",
        )

        result = service.process_all_batch_results(str(tmp_path))

        # Only original should be processed
        assert len(result) == 1


class TestProcessAllBatchResultsToleratesEmptyWhenRecoveryPending:
    """Tests for empty tolerance when recovery batches are in flight."""

    def test_returns_empty_list_when_recovery_in_progress(self, tmp_path):
        """Should return [] without raising when recovery batches are pending."""
        from agent_actions.llm.batch.core.batch_models import (
            BatchJobEntry,
            BatchRegistryStats,
        )
        from agent_actions.llm.batch.services.processing import (
            BatchProcessingService,
        )

        # Recovery entry still in progress
        recovery_entry = MagicMock(spec=BatchJobEntry)
        recovery_entry.batch_id = "batch_retry_1"
        recovery_entry.parent_file_name = "original.json"
        recovery_entry.recovery_type = "retry"

        manager = MagicMock()
        manager.get_all_jobs.return_value = {
            "original.json_retry_1": recovery_entry,
        }
        manager.get_registry_stats.return_value = BatchRegistryStats(
            total_jobs=1, completed=0, failed=0, in_progress=1, cancelled=0
        )

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        # Should NOT raise — recovery is pending
        result = service.process_all_batch_results(str(tmp_path))
        assert result == []


class TestCheckAndSubmitReprompt:
    """Tests for _check_and_submit_reprompt bool return."""

    def test_returns_true_when_no_reprompt_config(self):
        """Should return True (continue) when reprompt is not configured."""
        from agent_actions.llm.batch.services.processing import BatchProcessingService

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
        )

        result = service._check_and_submit_reprompt(
            batch_results=[],
            context_map={},
            output_directory="/tmp",
            file_name="test",
            entry=MagicMock(),
            agent_config=None,
            manager=MagicMock(),
            provider=MagicMock(),
        )

        assert result is True

    def test_returns_true_when_all_pass_validation(self):
        """Should return True when all results pass validation."""
        from agent_actions.llm.batch.services.processing import BatchProcessingService

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
        )
        # validate_results returns no failures
        service._retry_service = MagicMock()
        service._retry_service.validate_results.return_value = ([], "check")

        result = service._check_and_submit_reprompt(
            batch_results=[MagicMock()],
            context_map={},
            output_directory="/tmp",
            file_name="test",
            entry=MagicMock(),
            agent_config={"reprompt": {"validation": "check", "max_attempts": 2}},
            manager=MagicMock(),
            provider=MagicMock(),
        )

        assert result is True

    def test_returns_false_when_reprompt_submitted(self):
        """Should return False when a reprompt batch is submitted."""
        from agent_actions.llm.batch.infrastructure.recovery_state import (
            RecoveryStateManager,
        )
        from agent_actions.llm.batch.services.processing import BatchProcessingService

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
        )

        failed = MagicMock()
        failed.custom_id = "x"
        service._retry_service = MagicMock()
        service._retry_service.validate_results.return_value = ([failed], "check")
        service._retry_service.submit_reprompt_batch.return_value = (
            "reprompt-1",
            1,
        )

        with patch.object(RecoveryStateManager, "save"):
            result = service._check_and_submit_reprompt(
                batch_results=[failed],
                context_map={"x": {}},
                output_directory="/tmp",
                file_name="test",
                entry=MagicMock(provider="openai"),
                agent_config={"reprompt": {"validation": "check", "max_attempts": 2}},
                manager=MagicMock(),
                provider=MagicMock(),
            )

        assert result is False

    def test_returns_true_when_reprompt_exhausted(self):
        """Should return True and apply metadata when attempts exhausted."""
        from agent_actions.llm.batch.infrastructure.recovery_state import (
            RecoveryState,
        )
        from agent_actions.llm.batch.services.processing import BatchProcessingService

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
        )

        failed = MagicMock()
        failed.custom_id = "x"
        service._retry_service = MagicMock()
        service._retry_service.validate_results.return_value = ([failed], "check")

        state = RecoveryState(phase="reprompt", reprompt_attempt=2)

        result = service._check_and_submit_reprompt(
            batch_results=[failed],
            context_map={"x": {}},
            output_directory="/tmp",
            file_name="test",
            entry=MagicMock(provider="openai"),
            agent_config={"reprompt": {"validation": "check", "max_attempts": 2}},
            manager=MagicMock(),
            provider=MagicMock(),
            recovery_state=state,
        )

        assert result is True
        service._retry_service.apply_exhausted_reprompt_metadata.assert_called_once()


class TestCleanupRecoveryEntries:
    """Tests for _cleanup_recovery_entries after finalization."""

    def test_removes_linked_recovery_entries(self):
        """Should remove all recovery entries linked to the parent file."""
        from agent_actions.llm.batch.services.processing import BatchProcessingService

        parent_entry = MagicMock()
        parent_entry.parent_file_name = None

        retry_entry = MagicMock()
        retry_entry.parent_file_name = "original.jsonl"

        reprompt_entry = MagicMock()
        reprompt_entry.parent_file_name = "original.jsonl"

        unrelated_entry = MagicMock()
        unrelated_entry.parent_file_name = "other.jsonl"

        manager = MagicMock()
        manager.get_all_jobs.return_value = {
            "original.jsonl": parent_entry,
            "original.jsonl_retry_1": retry_entry,
            "original.jsonl_reprompt_1": reprompt_entry,
            "other.jsonl_retry_1": unrelated_entry,
        }

        BatchProcessingService._cleanup_recovery_entries(manager, "original.jsonl")

        assert manager.remove_batch_job.call_count == 2
        removed = {c.args[0] for c in manager.remove_batch_job.call_args_list}
        assert removed == {
            "original.jsonl_retry_1",
            "original.jsonl_reprompt_1",
        }


# ---------------------------------------------------------------------------
# Integration tests for process_batch() / process_all_batch_results()
# ---------------------------------------------------------------------------


class TestProcessBatchIntegrationHappyPath:
    """Integration tests exercising real BatchResultProcessor through process_all_batch_results."""

    def test_happy_path_processes_results_through_real_pipeline(self, tmp_path):
        """End-to-end: completed batch with 2 records produces correct workflow output.

        Uses a real BatchResultProcessor (not mocked) so the enrichment pipeline,
        reconciler, and data transformer all execute.  Only external boundaries
        (provider, registry, context manager, storage backend) are mocked.
        """
        from agent_actions.llm.batch.core.batch_constants import BatchStatus, FilterStatus
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.infrastructure.context import BatchContextManager
        from agent_actions.llm.batch.processing.result_processor import BatchResultProcessor
        from agent_actions.llm.batch.services.processing import BatchProcessingService
        from agent_actions.llm.providers.batch_base import BatchResult

        # --- realistic context map (2 records, both "included") ---
        context_map = {
            "rec_001": {
                "source_guid": "guid-aaa",
                "content": {"question": "What is 2+2?"},
                "_batch_filter_status": str(FilterStatus.INCLUDED),
            },
            "rec_002": {
                "source_guid": "guid-bbb",
                "content": {"question": "What is 3+3?"},
                "_batch_filter_status": str(FilterStatus.INCLUDED),
            },
        }

        # --- provider returns 2 successful results ---
        batch_result_1 = BatchResult(
            custom_id="rec_001",
            content={"answer": "4"},
            success=True,
            metadata=None,
        )
        batch_result_2 = BatchResult(
            custom_id="rec_002",
            content={"answer": "6"},
            success=True,
            metadata=None,
        )

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        provider.retrieve_results.return_value = [batch_result_1, batch_result_2]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        # --- context manager returns our context map ---
        context_manager = MagicMock(spec=BatchContextManager)
        context_manager.load_batch_context_map.return_value = context_map

        # --- registry with one completed entry ---
        entry = BatchJobEntry(
            batch_id="batch_happy_001",
            status=BatchStatus.COMPLETED,
            timestamp="2024-06-01T00:00:00Z",
            provider="openai",
            record_count=2,
            file_name="qa_extract.jsonl",
            parent_file_name=None,
            recovery_type=None,
        )

        manager = MagicMock()
        manager.get_all_jobs.return_value = {"qa_extract.jsonl": entry}
        manager.get_batch_job_by_id.return_value = entry

        # --- storage backend captures written output ---
        written_records: list[dict] = []

        def capture_write(action_name, relative_path, data):
            written_records.extend(data)

        mock_storage = MagicMock()
        mock_storage.write_target = capture_write
        mock_storage.set_disposition = MagicMock()

        # --- build service with REAL result processor ---
        real_processor = BatchResultProcessor()

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            result_processor=real_processor,
            registry_manager_factory=MagicMock(return_value=manager),
            storage_backend=mock_storage,
            action_name="extract_qa",
        )

        result_files = service.process_all_batch_results(str(tmp_path))

        # -- assertions --
        assert len(result_files) == 1, "Should produce exactly one output file"
        assert "qa_extract.json" in result_files[0]

        # Storage backend received the processed records
        assert len(written_records) == 2, "Should write 2 processed records"

        # Each record should have content and source_guid from the pipeline
        for record in written_records:
            assert "content" in record, "Processed record must have 'content'"
            assert "source_guid" in record, "Processed record must have 'source_guid'"
            assert record["source_guid"] in ("guid-aaa", "guid-bbb")

        # Verify the actual content was transformed (answer should appear)
        contents = [r["content"] for r in written_records]
        answers = set()
        for c in contents:
            if isinstance(c, dict) and "answer" in c:
                answers.add(c["answer"])
        assert answers == {"4", "6"}, f"Expected answers {{4, 6}}, got {answers}"

        # Provider was called correctly
        provider.retrieve_results.assert_called_once_with("batch_happy_001", str(tmp_path))
        provider.check_status.assert_called_with("batch_happy_001")

    def test_happy_path_with_skipped_record_produces_passthrough(self, tmp_path):
        """Records marked as SKIPPED in context_map should appear as passthrough tombstones."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus, FilterStatus
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.infrastructure.context import BatchContextManager
        from agent_actions.llm.batch.processing.result_processor import BatchResultProcessor
        from agent_actions.llm.batch.services.processing import BatchProcessingService
        from agent_actions.llm.providers.batch_base import BatchResult

        # 2 records: one included, one skipped by guard
        context_map = {
            "rec_001": {
                "source_guid": "guid-aaa",
                "content": {"question": "What is 2+2?"},
                "_batch_filter_status": str(FilterStatus.INCLUDED),
            },
            "rec_002": {
                "source_guid": "guid-bbb",
                "content": {"question": "Skip me"},
                "_batch_filter_status": str(FilterStatus.SKIPPED),
            },
        }

        # Provider returns only the included record
        batch_result_1 = BatchResult(
            custom_id="rec_001",
            content={"answer": "4"},
            success=True,
            metadata=None,
        )

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        provider.retrieve_results.return_value = [batch_result_1]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        context_manager = MagicMock(spec=BatchContextManager)
        context_manager.load_batch_context_map.return_value = context_map

        entry = BatchJobEntry(
            batch_id="batch_skip_001",
            status=BatchStatus.COMPLETED,
            timestamp="2024-06-01T00:00:00Z",
            provider="openai",
            record_count=2,
            parent_file_name=None,
            recovery_type=None,
        )

        manager = MagicMock()
        manager.get_all_jobs.return_value = {"mixed_batch.jsonl": entry}

        written_records: list[dict] = []

        def capture_write(action_name, relative_path, data):
            written_records.extend(data)

        mock_storage = MagicMock()
        mock_storage.write_target = capture_write
        mock_storage.set_disposition = MagicMock()

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            result_processor=BatchResultProcessor(),
            registry_manager_factory=MagicMock(return_value=manager),
            storage_backend=mock_storage,
            action_name="extract_qa",
        )

        result_files = service.process_all_batch_results(str(tmp_path))

        assert len(result_files) == 1
        assert len(written_records) == 2, "Should write both processed + passthrough records"

        # Find the passthrough record
        passthrough = [r for r in written_records if r.get("_unprocessed")]
        assert len(passthrough) == 1, "Exactly one record should be passthrough"
        assert passthrough[0]["source_guid"] == "guid-bbb"
        assert passthrough[0]["metadata"]["reason"] == "guard_skipped"


class TestProcessBatchIntegrationErrorPaths:
    """Integration tests for error handling in batch processing."""

    def test_provider_returns_error_results(self, tmp_path):
        """When the LLM provider returns success=False, records appear as error items."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus, FilterStatus
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.infrastructure.context import BatchContextManager
        from agent_actions.llm.batch.processing.result_processor import BatchResultProcessor
        from agent_actions.llm.batch.services.processing import BatchProcessingService
        from agent_actions.llm.providers.batch_base import BatchResult

        context_map = {
            "rec_001": {
                "source_guid": "guid-aaa",
                "content": {"question": "What is 2+2?"},
                "_batch_filter_status": str(FilterStatus.INCLUDED),
            },
            "rec_002": {
                "source_guid": "guid-bbb",
                "content": {"question": "What is 3+3?"},
                "_batch_filter_status": str(FilterStatus.INCLUDED),
            },
        }

        # One success, one error from provider
        batch_result_ok = BatchResult(
            custom_id="rec_001",
            content={"answer": "4"},
            success=True,
            metadata=None,
        )
        batch_result_err = BatchResult(
            custom_id="rec_002",
            content=None,
            success=False,
            error="Rate limit exceeded",
            metadata=None,
        )

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        provider.retrieve_results.return_value = [batch_result_ok, batch_result_err]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        context_manager = MagicMock(spec=BatchContextManager)
        context_manager.load_batch_context_map.return_value = context_map

        entry = BatchJobEntry(
            batch_id="batch_err_001",
            status=BatchStatus.COMPLETED,
            timestamp="2024-06-01T00:00:00Z",
            provider="openai",
            record_count=2,
            parent_file_name=None,
            recovery_type=None,
        )

        manager = MagicMock()
        manager.get_all_jobs.return_value = {"error_batch.jsonl": entry}

        written_records: list[dict] = []

        def capture_write(action_name, relative_path, data):
            written_records.extend(data)

        mock_storage = MagicMock()
        mock_storage.write_target = capture_write
        mock_storage.set_disposition = MagicMock()

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            result_processor=BatchResultProcessor(),
            registry_manager_factory=MagicMock(return_value=manager),
            storage_backend=mock_storage,
            action_name="extract_qa",
        )

        result_files = service.process_all_batch_results(str(tmp_path))

        assert len(result_files) == 1
        assert len(written_records) == 2, "Should write both success + error records"

        # Identify the error record
        error_records = [r for r in written_records if r.get("error")]
        assert len(error_records) == 1
        assert "Rate limit exceeded" in error_records[0]["error"]
        assert error_records[0]["source_guid"] == "guid-bbb"

        # The successful record should have content
        ok_records = [r for r in written_records if not r.get("error")]
        assert len(ok_records) == 1
        assert ok_records[0]["source_guid"] == "guid-aaa"

    def test_provider_retrieve_raises_wraps_in_processing_error(self, tmp_path):
        """When provider.retrieve_results raises, error is caught and batch is skipped."""
        from agent_actions.errors import ProcessingError
        from agent_actions.llm.batch.core.batch_constants import BatchStatus
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.services.processing import BatchProcessingService

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        provider.retrieve_results.side_effect = RuntimeError("Connection reset by peer")

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {}

        entry = BatchJobEntry(
            batch_id="batch_crash_001",
            status=BatchStatus.COMPLETED,
            timestamp="2024-06-01T00:00:00Z",
            provider="openai",
            record_count=1,
            parent_file_name=None,
            recovery_type=None,
        )

        manager = MagicMock()
        manager.get_all_jobs.return_value = {"crash_batch.jsonl": entry}
        stats = MagicMock()
        stats.in_progress = 0
        manager.get_registry_stats.return_value = stats

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        # The exception in _process_single_batch_file is caught by the loop,
        # but since no files were processed and no recovery is pending,
        # process_all_batch_results raises ProcessingError.
        with pytest.raises(ProcessingError) as exc_info:
            service.process_all_batch_results(str(tmp_path))

        assert "No batch results were successfully processed" in str(exc_info.value)

    def test_process_batch_results_raises_on_incomplete_batch(self, tmp_path):
        """process_batch_results raises ProcessingError when batch is not completed."""
        from agent_actions.errors import ProcessingError
        from agent_actions.llm.batch.core.batch_constants import BatchStatus
        from agent_actions.llm.batch.services.processing import BatchProcessingService

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.FAILED

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        manager = MagicMock()

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        with pytest.raises(ProcessingError) as exc_info:
            service.process_batch_results(
                batch_id="batch_failed_001",
                output_directory=str(tmp_path),
                base_directory=str(tmp_path),
                file_path=str(tmp_path / "input.jsonl"),
            )

        assert "not completed" in str(exc_info.value)

    def test_all_results_malformed_content_none(self, tmp_path):
        """When all batch results have content=None and success=True, they become error items."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus, FilterStatus
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.infrastructure.context import BatchContextManager
        from agent_actions.llm.batch.processing.result_processor import BatchResultProcessor
        from agent_actions.llm.batch.services.processing import BatchProcessingService
        from agent_actions.llm.providers.batch_base import BatchResult

        context_map = {
            "rec_001": {
                "source_guid": "guid-aaa",
                "content": {"question": "What is 2+2?"},
                "_batch_filter_status": str(FilterStatus.INCLUDED),
            },
        }

        # Provider returns success=True but content=None (malformed)
        malformed_result = BatchResult(
            custom_id="rec_001",
            content=None,
            success=True,
            metadata=None,
        )

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        provider.retrieve_results.return_value = [malformed_result]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        context_manager = MagicMock(spec=BatchContextManager)
        context_manager.load_batch_context_map.return_value = context_map

        entry = BatchJobEntry(
            batch_id="batch_malformed_001",
            status=BatchStatus.COMPLETED,
            timestamp="2024-06-01T00:00:00Z",
            provider="openai",
            record_count=1,
            parent_file_name=None,
            recovery_type=None,
        )

        manager = MagicMock()
        manager.get_all_jobs.return_value = {"malformed.jsonl": entry}

        written_records: list[dict] = []

        def capture_write(action_name, relative_path, data):
            written_records.extend(data)

        mock_storage = MagicMock()
        mock_storage.write_target = capture_write
        mock_storage.set_disposition = MagicMock()

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            result_processor=BatchResultProcessor(),
            registry_manager_factory=MagicMock(return_value=manager),
            storage_backend=mock_storage,
            action_name="extract_qa",
        )

        result_files = service.process_all_batch_results(str(tmp_path))

        assert len(result_files) == 1
        assert len(written_records) == 1

        # success=True but content=None is treated as an error by BatchResultProcessor
        record = written_records[0]
        assert record.get("error"), "Malformed result (content=None) should produce an error item"
        assert record["source_guid"] == "guid-aaa"

    def test_process_batch_results_single_batch_happy_path(self, tmp_path):
        """process_batch_results (single batch API) produces correct output file."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus, FilterStatus
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.infrastructure.context import BatchContextManager
        from agent_actions.llm.batch.processing.result_processor import BatchResultProcessor
        from agent_actions.llm.batch.services.processing import BatchProcessingService
        from agent_actions.llm.providers.batch_base import BatchResult

        context_map = {
            "rec_001": {
                "source_guid": "guid-aaa",
                "content": {"question": "Capital of France?"},
                "_batch_filter_status": str(FilterStatus.INCLUDED),
            },
        }

        batch_result = BatchResult(
            custom_id="rec_001",
            content={"answer": "Paris"},
            success=True,
            metadata=None,
        )

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        provider.retrieve_results.return_value = [batch_result]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        entry = BatchJobEntry(
            batch_id="batch_single_001",
            status=BatchStatus.COMPLETED,
            timestamp="2024-06-01T00:00:00Z",
            provider="openai",
            record_count=1,
            file_name="geo_questions.jsonl",
        )

        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry

        context_manager = MagicMock(spec=BatchContextManager)
        context_manager.load_batch_context_map.return_value = context_map

        written_records: list[dict] = []

        def capture_write(action_name, relative_path, data):
            written_records.extend(data)

        mock_storage = MagicMock()
        mock_storage.write_target = capture_write
        mock_storage.set_disposition = MagicMock()

        # Create input file structure: base_dir/subdir/input.jsonl
        input_dir = tmp_path / "inputs"
        input_dir.mkdir()
        input_file = input_dir / "geo_questions.jsonl"
        input_file.write_text("")

        output_dir = tmp_path / "outputs"
        output_dir.mkdir()

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            result_processor=BatchResultProcessor(),
            registry_manager_factory=MagicMock(return_value=manager),
            storage_backend=mock_storage,
            action_name="extract_geo",
        )

        result_path = service.process_batch_results(
            batch_id="batch_single_001",
            output_directory=str(output_dir),
            base_directory=str(tmp_path),
            file_path=str(input_file),
        )

        assert result_path.endswith(".json")
        assert "geo_questions" in result_path
        assert len(written_records) == 1
        assert written_records[0]["source_guid"] == "guid-aaa"
