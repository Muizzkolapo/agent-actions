"""Tests for BatchRetryService.

TDD: These tests are written BEFORE the implementation to define
the expected behavior of the retry service.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Dict, Any, Optional


class TestBatchRetryServiceInit:
    """Tests for BatchRetryService initialization."""

    def test_init_with_all_dependencies(self):
        """Should initialize with all required dependencies."""
        from agent_actions.llm_invocation.batch.batch_retry_service import (
            BatchRetryService,
        )

        client_resolver = MagicMock()
        context_manager = MagicMock()
        registry_manager_factory = MagicMock()

        service = BatchRetryService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=registry_manager_factory,
        )

        assert service._client_resolver is client_resolver
        assert service._context_manager is context_manager
        assert service._registry_manager_factory is registry_manager_factory

    def test_init_with_optional_retry_config(self):
        """Should accept optional default retry config."""
        from agent_actions.llm_invocation.batch.batch_retry_service import (
            BatchRetryService,
        )
        from agent_actions.llm_invocation.batch.batch_retry_config import RetryConfig

        retry_config = RetryConfig(enabled=True, max_attempts=5)

        service = BatchRetryService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(),
            default_retry_config=retry_config,
        )

        assert service._default_retry_config is retry_config


class TestRetryBatchJobValidation:
    """Tests for retry_batch_job validation."""

    def test_raises_when_batch_not_found(self):
        """Should raise ProcessingError when batch not in registry."""
        from agent_actions.llm_invocation.batch.batch_retry_service import (
            BatchRetryService,
        )
        from agent_actions.errors import ProcessingError

        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = None

        service = BatchRetryService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        with pytest.raises(ProcessingError) as exc_info:
            service.retry_batch_job("batch_123", "/tmp/output")

        assert "not found in registry" in str(exc_info.value)

    def test_raises_when_batch_not_completed(self):
        """Should raise ProcessingError when batch status is not COMPLETED."""
        from agent_actions.llm_invocation.batch.batch_retry_service import (
            BatchRetryService,
        )
        from agent_actions.llm_invocation.batch.batch_constants import BatchStatus
        from agent_actions.errors import ProcessingError

        entry = MagicMock()
        entry.status = BatchStatus.IN_PROGRESS
        entry.batch_id = "batch_123"

        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry

        service = BatchRetryService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(return_value=manager),
        )

        with pytest.raises(ProcessingError) as exc_info:
            service.retry_batch_job("batch_123", "/tmp/output")

        assert "not completed" in str(exc_info.value)


class TestRetryBatchJobNoMissingRecords:
    """Tests for retry when no records are missing."""

    def test_returns_none_when_no_missing_records(self):
        """Should return None when all records are present."""
        from agent_actions.llm_invocation.batch.batch_retry_service import (
            BatchRetryService,
        )
        from agent_actions.llm_invocation.batch.batch_constants import BatchStatus

        # Setup entry
        entry = MagicMock()
        entry.status = BatchStatus.COMPLETED
        entry.batch_id = "batch_123"
        entry.record_count = 2

        # Setup manager
        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry
        manager.get_all_jobs.return_value = {"file1.jsonl": entry}

        # Setup context with 2 records
        context_map = {
            "record_1": {"_batch_filter_status": "included"},
            "record_2": {"_batch_filter_status": "included"},
        }

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = context_map

        # Setup provider that returns all 2 results
        provider = MagicMock()
        result1 = MagicMock()
        result1.custom_id = "record_1"
        result2 = MagicMock()
        result2.custom_id = "record_2"
        provider.retrieve_results.return_value = [result1, result2]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        service = BatchRetryService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=MagicMock(return_value=manager),
        )

        result = service.retry_batch_job("batch_123", "/tmp/output")

        assert result is None


class TestRetryBatchJobWithMissingRecords:
    """Tests for retry when records are missing."""

    def test_returns_retry_batch_id_on_success(self):
        """Should return new batch ID when retry is triggered."""
        from agent_actions.llm_invocation.batch.batch_retry_service import (
            BatchRetryService,
        )
        from agent_actions.llm_invocation.batch.batch_constants import BatchStatus
        from agent_actions.llm_invocation.batch.batch_retry_config import RetryConfig

        # Setup entry
        entry = MagicMock()
        entry.status = BatchStatus.COMPLETED
        entry.batch_id = "batch_123"
        entry.record_count = 2

        # Setup manager
        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry
        manager.get_all_jobs.return_value = {"file1.jsonl": entry}

        # Setup context with 2 records
        context_map = {
            "record_1": {"_batch_filter_status": "included"},
            "record_2": {"_batch_filter_status": "included"},
        }

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = context_map

        # Setup provider that returns only 1 result (1 missing)
        provider = MagicMock()
        result1 = MagicMock()
        result1.custom_id = "record_1"
        provider.retrieve_results.return_value = [result1]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        # Setup orchestrator mock
        orchestrator = MagicMock()
        retry_result = MagicMock()
        retry_result.retry_batch_ids = ["retry_batch_456"]
        retry_result.total_attempts = 1
        retry_result.final_success_count = 1
        retry_result.final_missing_count = 0
        orchestrator.orchestrate_retry_chain.return_value = retry_result

        service = BatchRetryService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=MagicMock(return_value=manager),
            default_retry_config=RetryConfig.default(),
        )

        # Patch the orchestrator creation
        with patch.object(service, "_get_retry_orchestrator", return_value=orchestrator):
            result = service.retry_batch_job("batch_123", "/tmp/output")

        assert result == "retry_batch_456"

    def test_uses_max_attempts_override(self):
        """Should use max_attempts parameter when provided."""
        from agent_actions.llm_invocation.batch.batch_retry_service import (
            BatchRetryService,
        )
        from agent_actions.llm_invocation.batch.batch_constants import BatchStatus
        from agent_actions.llm_invocation.batch.batch_retry_config import RetryConfig

        # Setup entry
        entry = MagicMock()
        entry.status = BatchStatus.COMPLETED
        entry.batch_id = "batch_123"
        entry.record_count = 2

        # Setup manager
        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry
        manager.get_all_jobs.return_value = {"file1.jsonl": entry}

        # Setup context
        context_map = {
            "record_1": {"_batch_filter_status": "included"},
            "record_2": {"_batch_filter_status": "included"},
        }

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = context_map

        # Setup provider (1 missing record)
        provider = MagicMock()
        result1 = MagicMock()
        result1.custom_id = "record_1"
        provider.retrieve_results.return_value = [result1]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        # Setup orchestrator
        orchestrator = MagicMock()
        retry_result = MagicMock()
        retry_result.retry_batch_ids = ["retry_batch_456"]
        retry_result.total_attempts = 1
        retry_result.final_success_count = 1
        retry_result.final_missing_count = 0
        orchestrator.orchestrate_retry_chain.return_value = retry_result

        service = BatchRetryService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=MagicMock(return_value=manager),
            default_retry_config=RetryConfig(enabled=True, max_attempts=3),
        )

        with patch.object(service, "_get_retry_orchestrator", return_value=orchestrator):
            service.retry_batch_job("batch_123", "/tmp/output", max_attempts=10)

        # Verify orchestrator was called with overridden max_attempts
        call_kwargs = orchestrator.orchestrate_retry_chain.call_args[1]
        assert call_kwargs["retry_config"].max_attempts == 10


class TestRetryBatchJobFileNameResolution:
    """Tests for file name resolution in retry."""

    def test_finds_file_name_from_registry(self):
        """Should find correct file_name from registry."""
        from agent_actions.llm_invocation.batch.batch_retry_service import (
            BatchRetryService,
        )
        from agent_actions.llm_invocation.batch.batch_constants import BatchStatus

        entry = MagicMock()
        entry.status = BatchStatus.COMPLETED
        entry.batch_id = "batch_123"
        entry.record_count = 1

        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry
        manager.get_all_jobs.return_value = {"my_file.jsonl": entry}

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {}

        provider = MagicMock()
        provider.retrieve_results.return_value = []

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        service = BatchRetryService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=MagicMock(return_value=manager),
        )

        # No missing records, returns None
        result = service.retry_batch_job("batch_123", "/tmp/output")

        # Verify context was loaded with correct file name
        context_manager.load_batch_context_map.assert_called_once_with(
            "/tmp/output", "my_file.jsonl"
        )

    def test_defaults_to_default_when_file_not_found(self):
        """Should use 'default' when file_name not found in registry."""
        from agent_actions.llm_invocation.batch.batch_retry_service import (
            BatchRetryService,
        )
        from agent_actions.llm_invocation.batch.batch_constants import BatchStatus

        entry = MagicMock()
        entry.status = BatchStatus.COMPLETED
        entry.batch_id = "batch_123"
        entry.record_count = 1

        other_entry = MagicMock()
        other_entry.batch_id = "other_batch"

        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry
        # Registry has different batch
        manager.get_all_jobs.return_value = {"other_file.jsonl": other_entry}

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {}

        provider = MagicMock()
        provider.retrieve_results.return_value = []

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        service = BatchRetryService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=MagicMock(return_value=manager),
        )

        service.retry_batch_job("batch_123", "/tmp/output")

        # Verify context was loaded with 'default'
        context_manager.load_batch_context_map.assert_called_once_with("/tmp/output", "default")
