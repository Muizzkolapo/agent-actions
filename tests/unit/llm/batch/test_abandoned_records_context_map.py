"""Tests for _fail_abandoned_records when context_map lookup fails.

Covers the error path where load_batch_context_map raises an exception,
verifying that the function logs a warning and returns without writing
any dispositions (records may remain with stale DEFERRED dispositions).
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys, FilterStatus
from agent_actions.llm.batch.services.processing import BatchProcessingService


@pytest.fixture
def processing_service():
    """Create a BatchProcessingService with mocked dependencies."""
    client_resolver = MagicMock()
    context_manager = MagicMock()
    result_processor = MagicMock()
    registry_manager_factory = MagicMock()
    storage_backend = MagicMock()

    service = BatchProcessingService(
        client_resolver=client_resolver,
        context_manager=context_manager,
        result_processor=result_processor,
        registry_manager_factory=registry_manager_factory,
        storage_backend=storage_backend,
        action_name="test_action",
    )
    return service


class TestFailAbandonedRecordsContextMapFailure:
    """Tests for _fail_abandoned_records when context_map is unavailable."""

    def test_context_map_load_exception_logs_warning_and_returns(self, processing_service):
        """When load_batch_context_map raises, function logs warning and returns."""
        processing_service._context_manager.load_batch_context_map.side_effect = FileNotFoundError(
            "context map not found"
        )

        # Should not raise — function catches the exception
        processing_service._fail_abandoned_records(
            file_name="batch_001.jsonl",
            output_directory="/tmp/output",
            action_name="test_action",
            error=RuntimeError("batch crashed"),
        )

        # No disposition writes should have occurred
        processing_service._storage_backend.clear_disposition.assert_not_called()
        processing_service._storage_backend.set_disposition.assert_not_called()

    def test_context_map_load_generic_exception_does_not_raise(self, processing_service):
        """Any exception type from context_map load is caught (not propagated)."""
        processing_service._context_manager.load_batch_context_map.side_effect = RuntimeError(
            "unexpected error"
        )

        # Should not raise
        processing_service._fail_abandoned_records(
            file_name="batch_002.jsonl",
            output_directory="/tmp/output",
            action_name="test_action",
            error=ValueError("processing failed"),
        )

        # Verify no disposition writes occurred
        processing_service._storage_backend.clear_disposition.assert_not_called()

    def test_no_storage_backend_returns_immediately(self, processing_service):
        """When storage_backend is None, function returns without loading context."""
        processing_service._storage_backend = None

        processing_service._fail_abandoned_records(
            file_name="batch_003.jsonl",
            output_directory="/tmp/output",
            action_name="test_action",
            error=RuntimeError("crash"),
        )

        # Context manager should not even be called
        processing_service._context_manager.load_batch_context_map.assert_not_called()

    def test_no_action_name_returns_immediately(self, processing_service):
        """When action_name is None, function returns without loading context."""
        processing_service._fail_abandoned_records(
            file_name="batch_004.jsonl",
            output_directory="/tmp/output",
            action_name=None,
            error=RuntimeError("crash"),
        )

        processing_service._context_manager.load_batch_context_map.assert_not_called()

    def test_successful_context_map_writes_failed_dispositions(self, processing_service):
        """Happy path: included records get FAILED dispositions written."""
        context_map = {
            "id_1": {
                ContextMetaKeys.FILTER_STATUS: str(FilterStatus.INCLUDED),
                "source_guid": "guid_1",
            },
            "id_2": {
                ContextMetaKeys.FILTER_STATUS: str(FilterStatus.SKIPPED),
                "source_guid": "guid_2",
            },
            "id_3": {
                ContextMetaKeys.FILTER_STATUS: str(FilterStatus.INCLUDED),
                "source_guid": "guid_3",
            },
        }
        processing_service._context_manager.load_batch_context_map.return_value = context_map

        processing_service._fail_abandoned_records(
            file_name="batch_005.jsonl",
            output_directory="/tmp/output",
            action_name="test_action",
            error=RuntimeError("batch exploded"),
        )

        # Should clear DEFERRED for included records only (guid_1, guid_3)
        assert processing_service._storage_backend.clear_disposition.call_count == 2
