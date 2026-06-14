"""Tests for _fail_abandoned_records when context_map lookup fails.

Covers the error path where load_batch_context_map raises an exception,
verifying that the function returns without writing any dispositions.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys, FilterStatus
from agent_actions.llm.batch.services.processing import BatchProcessingService


@pytest.fixture
def processing_service():
    """Create a BatchProcessingService with mocked dependencies."""
    return BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=MagicMock(),
        storage_backend=MagicMock(),
        workflow_name="test_action",
    )


class TestFailAbandonedRecordsContextMapFailure:
    """Tests for _fail_abandoned_records when context_map is unavailable."""

    @pytest.mark.parametrize(
        "exception",
        [FileNotFoundError("context map not found"), RuntimeError("unexpected error")],
        ids=["file_not_found", "runtime_error"],
    )
    def test_context_map_load_exception_catches_and_skips_dispositions(
        self, processing_service, exception
    ):
        """Any exception from load_batch_context_map is caught; no dispositions written."""
        processing_service._context_manager.load_batch_context_map.side_effect = exception

        processing_service._fail_abandoned_records(
            file_name="batch_001.jsonl",
            output_directory="/tmp/output",
            action_name="test_action",
            error=RuntimeError("batch crashed"),
        )

        processing_service._storage_backend.clear_disposition.assert_not_called()
        processing_service._storage_backend.set_disposition.assert_not_called()

    @pytest.mark.parametrize("attr,value", [("_storage_backend", None)], ids=["no_backend"])
    def test_no_storage_backend_returns_immediately(self, processing_service, attr, value):
        """When storage_backend is None, context_map is never loaded."""
        setattr(processing_service, attr, value)

        processing_service._fail_abandoned_records(
            file_name="batch.jsonl",
            output_directory="/tmp/output",
            action_name="test_action",
            error=RuntimeError("crash"),
        )

        processing_service._context_manager.load_batch_context_map.assert_not_called()

    def test_no_action_name_returns_immediately(self, processing_service):
        """When action_name is None, context_map is never loaded."""
        processing_service._fail_abandoned_records(
            file_name="batch.jsonl",
            output_directory="/tmp/output",
            action_name=None,
            error=RuntimeError("crash"),
        )

        processing_service._context_manager.load_batch_context_map.assert_not_called()

    def test_successful_context_map_writes_failed_dispositions(self, processing_service):
        """Included records get DEFERRED cleared; skipped records are ignored."""
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

        assert processing_service._storage_backend.clear_disposition.call_count == 2
