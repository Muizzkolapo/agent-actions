"""Tests for BatchProcessingService.

TDD: These tests are written BEFORE the implementation to define
the expected behavior of the processing service.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestBatchProcessingServiceInit:
    """Tests for BatchProcessingService initialization."""

    def test_init_with_all_dependencies(self):
        """Should initialize with all required dependencies."""
        from agent_actions.llm_invocation.batch.services.batch_processing_service import (
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
        from agent_actions.llm_invocation.batch.services.batch_processing_service import (
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
        from agent_actions.llm_invocation.batch.services.batch_processing_service import (
            BatchProcessingService,
        )
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

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
        from agent_actions.llm_invocation.batch.services.batch_processing_service import (
            BatchProcessingService,
        )
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

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
        from agent_actions.llm_invocation.batch.services.batch_processing_service import (
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
        from agent_actions.llm_invocation.batch.services.batch_processing_service import (
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
        from agent_actions.llm_invocation.batch.services.batch_processing_service import (
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
        """Should write main output to JSON file."""
        from agent_actions.llm_invocation.batch.services.batch_processing_service import (
            BatchProcessingService,
        )

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
        )

        main_output = [{"id": "1", "result": "success"}]
        output_file = tmp_path / "output.json"

        service._write_batch_output(
            output_file=output_file,
            main_output=main_output,
            side_output_data=None,
            output_directory=str(tmp_path),
        )

        assert output_file.exists()
        with open(output_file) as f:
            written_data = json.load(f)
        assert written_data == main_output


class TestProcessAllBatchResults:
    """Tests for process_all_batch_results method."""

    def test_raises_when_no_registry(self):
        """Should raise ProcessingError when no registry found."""
        from agent_actions.llm_invocation.batch.services.batch_processing_service import (
            BatchProcessingService,
        )
        from agent_actions.errors import ProcessingError

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
        from agent_actions.llm_invocation.batch.services.batch_processing_service import (
            BatchProcessingService,
        )
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus
        from agent_actions.errors import ProcessingError

        # Setup entry that is not completed
        entry = MagicMock()
        entry.batch_id = "batch_123"
        entry.status = BatchStatus.IN_PROGRESS

        manager = MagicMock()
        manager.get_all_jobs.return_value = {"file1.jsonl": entry}

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
        from agent_actions.llm_invocation.batch.services.batch_processing_service import (
            BatchProcessingService,
        )
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        # Setup completed entry
        entry = MagicMock()
        entry.batch_id = "batch_123"
        entry.record_count = 1

        manager = MagicMock()
        manager.get_all_jobs.return_value = {"file1.jsonl": entry}

        # Provider returns completed status and results
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        result1 = MagicMock()
        result1.custom_id = "record_1"
        result1.content = {"answer": "test"}
        provider.retrieve_results.return_value = [result1]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {}

        result_processor = MagicMock()
        result_processor.process.return_value = [{"id": "1", "result": "done"}]

        service = BatchProcessingService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            result_processor=result_processor,
            registry_manager_factory=MagicMock(return_value=manager),
        )

        result = service.process_all_batch_results(str(tmp_path))

        assert len(result) == 1
        assert "file1.json" in result[0]


class TestProcessBatchResults:
    """Tests for process_batch_results method."""

    def test_raises_when_not_completed(self):
        """Should raise ProcessingError when batch not completed."""
        from agent_actions.llm_invocation.batch.services.batch_processing_service import (
            BatchProcessingService,
        )
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus
        from agent_actions.errors import ProcessingError

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
