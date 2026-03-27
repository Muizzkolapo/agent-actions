"""Tests for BatchContextAdapter."""

from agent_actions.processing.batch_context_adapter import BatchContextAdapter
from agent_actions.processing.types import (
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)


class TestToProcessingResult:
    """Test BatchContextAdapter.to_processing_result."""

    def test_creates_success_result(self):
        data = [{"content": {"key": "val"}, "source_guid": "sg1"}]
        result = BatchContextAdapter.to_processing_result(
            data=data,
            source_guid="sg1",
        )
        assert result.status == ProcessingStatus.SUCCESS
        assert result.executed is True
        assert result.data is data

    def test_maps_recovery_metadata(self):
        recovery = RecoveryMetadata(
            retry=RetryMetadata(attempts=3, failures=2, succeeded=True, reason="timeout")
        )
        result = BatchContextAdapter.to_processing_result(
            data=[],
            source_guid="sg1",
            recovery_metadata=recovery,
        )
        assert result.recovery_metadata is recovery

    def test_maps_passthrough_fields(self):
        passthrough = {"extra_field": "value"}
        result = BatchContextAdapter.to_processing_result(
            data=[],
            source_guid="sg1",
            passthrough_fields=passthrough,
        )
        assert result.passthrough_fields == passthrough
