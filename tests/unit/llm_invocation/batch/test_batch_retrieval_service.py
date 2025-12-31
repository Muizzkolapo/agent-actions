"""Tests for BatchRetrievalService.

TDD: These tests are written BEFORE the implementation to define
the expected behavior of the retrieval service.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestBatchRetrievalServiceInit:
    """Tests for BatchRetrievalService initialization."""

    def test_init_with_all_dependencies(self):
        """Should initialize with all required dependencies."""
        from agent_actions.llm_invocation.batch.services.batch_retrieval_service import (
            BatchRetrievalService,
        )

        client_resolver = MagicMock()
        context_manager = MagicMock()
        registry_manager_factory = MagicMock()

        service = BatchRetrievalService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=registry_manager_factory,
        )

        assert service._client_resolver is client_resolver
        assert service._context_manager is context_manager
        assert service._registry_manager_factory is registry_manager_factory


class TestRetrieveResults:
    """Tests for retrieve_results method."""

    def test_retrieves_and_writes_results_to_jsonl(self, tmp_path):
        """Should retrieve results and write to JSONL file."""
        from agent_actions.llm_invocation.batch.services.batch_retrieval_service import (
            BatchRetrievalService,
        )

        # Setup entry
        entry = MagicMock()
        entry.file_name = "test_file.jsonl"
        entry.record_count = 2

        # Setup manager
        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry

        # Setup context
        context_map = {"record_1": {}, "record_2": {}}
        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = context_map

        # Setup provider with results
        provider = MagicMock()
        result1 = MagicMock()
        result1.custom_id = "record_1"
        result1.content = {"answer": "hello"}
        result1.usage = {"tokens": 10}
        result2 = MagicMock()
        result2.custom_id = "record_2"
        result2.content = {"answer": "world"}
        result2.usage = {"tokens": 15}
        provider.retrieve_results.return_value = [result1, result2]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        service = BatchRetrievalService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=MagicMock(return_value=manager),
        )

        result_file = service.retrieve_results("batch_123", str(tmp_path))

        # Verify file was created
        assert Path(result_file).exists()
        assert str(result_file).endswith("_results.jsonl")

        # Verify JSONL content
        with open(result_file) as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_uses_file_path_stem_for_output_name(self, tmp_path):
        """Should use file_path stem for output file name when provided."""
        from agent_actions.llm_invocation.batch.services.batch_retrieval_service import (
            BatchRetrievalService,
        )

        entry = MagicMock()
        entry.file_name = None
        entry.record_count = 1

        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {}

        provider = MagicMock()
        result1 = MagicMock()
        result1.custom_id = "record_1"
        result1.content = {}
        result1.usage = {}
        provider.retrieve_results.return_value = [result1]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        service = BatchRetrievalService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=MagicMock(return_value=manager),
        )

        result_file = service.retrieve_results(
            "batch_123", str(tmp_path), file_path="/input/my_data.jsonl"
        )

        assert "my_data_results.jsonl" in str(result_file)

    def test_uses_batch_id_for_output_when_no_file_path(self, tmp_path):
        """Should use batch_id for output name when file_path not provided."""
        from agent_actions.llm_invocation.batch.services.batch_retrieval_service import (
            BatchRetrievalService,
        )

        entry = MagicMock()
        entry.file_name = None
        entry.record_count = 1

        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {}

        provider = MagicMock()
        result1 = MagicMock()
        result1.custom_id = "record_1"
        result1.content = {}
        result1.usage = {}
        provider.retrieve_results.return_value = [result1]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        service = BatchRetrievalService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=MagicMock(return_value=manager),
        )

        result_file = service.retrieve_results("batch_123", str(tmp_path))

        assert "batch_123_results.jsonl" in str(result_file)

    def test_skips_write_if_file_exists(self, tmp_path):
        """Should not overwrite existing results file."""
        from agent_actions.llm_invocation.batch.services.batch_retrieval_service import (
            BatchRetrievalService,
        )

        # Create existing file
        existing_file = tmp_path / "batch_123_results.jsonl"
        existing_file.write_text("existing content\n")

        entry = MagicMock()
        entry.file_name = None
        entry.record_count = 1

        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {}

        provider = MagicMock()
        result1 = MagicMock()
        result1.custom_id = "record_1"
        result1.content = {"new": "data"}
        result1.usage = {}
        provider.retrieve_results.return_value = [result1]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        service = BatchRetrievalService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=MagicMock(return_value=manager),
        )

        result_file = service.retrieve_results("batch_123", str(tmp_path))

        # Verify original content preserved
        assert Path(result_file).read_text() == "existing content\n"

    def test_raises_external_service_error_on_failure(self, tmp_path):
        """Should raise ExternalServiceError when retrieval fails."""
        from agent_actions.llm_invocation.batch.services.batch_retrieval_service import (
            BatchRetrievalService,
        )
        from agent_actions.errors import ExternalServiceError

        manager = MagicMock()
        manager.get_batch_job_by_id.side_effect = Exception("API error")

        service = BatchRetrievalService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        with pytest.raises(ExternalServiceError):
            service.retrieve_results("batch_123", str(tmp_path))


class TestRetrieveResultsContextLoading:
    """Tests for context map loading in retrieve_results."""

    def test_loads_context_when_file_name_present(self, tmp_path):
        """Should load context map when entry has file_name."""
        from agent_actions.llm_invocation.batch.services.batch_retrieval_service import (
            BatchRetrievalService,
        )

        entry = MagicMock()
        entry.file_name = "my_batch.jsonl"
        entry.record_count = 1

        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {}

        provider = MagicMock()
        provider.retrieve_results.return_value = []

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        service = BatchRetrievalService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=MagicMock(return_value=manager),
        )

        service.retrieve_results("batch_123", str(tmp_path))

        context_manager.load_batch_context_map.assert_called_once_with(
            str(tmp_path), "my_batch.jsonl"
        )

    def test_uses_empty_context_when_no_file_name(self, tmp_path):
        """Should use empty context when entry has no file_name."""
        from agent_actions.llm_invocation.batch.services.batch_retrieval_service import (
            BatchRetrievalService,
        )

        entry = MagicMock()
        entry.file_name = None
        entry.record_count = 1

        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {}

        provider = MagicMock()
        provider.retrieve_results.return_value = []

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        service = BatchRetrievalService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=MagicMock(return_value=manager),
        )

        service.retrieve_results("batch_123", str(tmp_path))

        # Should not load context
        context_manager.load_batch_context_map.assert_not_called()
