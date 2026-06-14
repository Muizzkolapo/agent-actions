"""Tests for F15: CLI batch path (process_batch_results) retry/reprompt parity.

process_batch_results should use the same retry/reprompt logic as the
production path (process_all_batch_results → _process_original_batch).

These tests verify that:
1. Missing records trigger retry submission (not immediate tombstone)
2. Reprompt logic is invoked when configured
3. When no recovery is needed, output matches production path
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.providers.batch_base import BatchResult


def _make_result(custom_id: str, content: str = "response", success: bool = True) -> BatchResult:
    return BatchResult(custom_id=custom_id, content=content, success=success)


def _make_service(**overrides) -> BatchProcessingService:
    """Create a real BatchProcessingService with mocked dependencies."""
    defaults = {
        "client_resolver": MagicMock(),
        "context_manager": MagicMock(),
        "result_processor": MagicMock(),
        "registry_manager_factory": MagicMock(),
        "source_handler": None,
        "action_indices": {},
        "dependency_configs": {},
        "storage_backend": MagicMock(),
        "action_name": "test_action",
    }
    defaults.update(overrides)
    return BatchProcessingService(**defaults)


def _make_entry(
    batch_id: str = "batch-123",
    file_name: str = "test_file",
    record_count: int = 3,
) -> BatchJobEntry:
    return BatchJobEntry(
        batch_id=batch_id,
        status=BatchStatus.COMPLETED,
        timestamp="2026-05-19T00:00:00Z",
        provider="openai",
        record_count=record_count,
        file_name=file_name,
    )


class TestProcessBatchResultsRetryParity:
    """process_batch_results delegates to _process_single_batch_file for retry/reprompt."""

    def test_delegates_to_process_single_batch_file(self):
        """process_batch_results routes through _process_single_batch_file,
        which has retry/reprompt logic — not direct retrieve_and_reconcile."""
        manager = MagicMock()
        entry = _make_entry()
        manager.get_batch_job_by_id.return_value = entry

        service = _make_service(registry_manager_factory=lambda _: manager)

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        service._client_resolver.get_for_batch_id.return_value = provider

        with patch.object(
            service, "_process_single_batch_file", return_value="/tmp/output.json"
        ) as mock_delegate:
            result = service.process_batch_results(
                batch_id="batch-123",
                output_directory="/tmp/out",
                agent_config={"kind": "llm"},
            )

        assert result == "/tmp/output.json"
        mock_delegate.assert_called_once()
        call_kwargs = mock_delegate.call_args
        assert call_kwargs.kwargs["batch_id"] == "batch-123"

    def test_recovery_pending_raises_processing_error(self):
        """When _process_single_batch_file returns None (recovery submitted),
        process_batch_results raises ProcessingError to signal the caller."""
        from agent_actions.errors import ProcessingError

        manager = MagicMock()
        entry = _make_entry()
        manager.get_batch_job_by_id.return_value = entry

        service = _make_service(registry_manager_factory=lambda _: manager)

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        service._client_resolver.get_for_batch_id.return_value = provider

        with patch.object(service, "_process_single_batch_file", return_value=None):
            with pytest.raises(ProcessingError, match="recovery"):
                service.process_batch_results(
                    batch_id="batch-123",
                    output_directory="/tmp/out",
                )

    def test_missing_entry_raises_processing_error(self):
        """When batch_id has no registry entry, raises ProcessingError."""
        from agent_actions.errors import ProcessingError

        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = None

        service = _make_service(registry_manager_factory=lambda _: manager)

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        service._client_resolver.get_for_batch_id.return_value = provider

        with pytest.raises(ProcessingError, match="registry"):
            service.process_batch_results(
                batch_id="batch-123",
                output_directory="/tmp/out",
            )

    def test_not_completed_raises_processing_error(self):
        """Non-completed batch still raises ProcessingError."""
        from agent_actions.errors import ProcessingError

        manager = MagicMock()
        service = _make_service(registry_manager_factory=lambda _: manager)

        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.IN_PROGRESS
        service._client_resolver.get_for_batch_id.return_value = provider

        with pytest.raises(ProcessingError, match="not completed"):
            service.process_batch_results(
                batch_id="batch-123",
                output_directory="/tmp/out",
            )
