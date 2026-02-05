"""Tests for BatchContextAdapter."""

import pytest

from agent_actions.processing.batch_context_adapter import BatchContextAdapter
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingMode,
    ProcessingResult,
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)


class TestToProcessingContext:
    """Test BatchContextAdapter.to_processing_context."""

    def test_maps_agent_config(self):
        config = {"agent_type": "transform", "model": "gpt-4"}
        ctx = BatchContextAdapter.to_processing_context(
            agent_config=config,
            original_row={"source_guid": "sg1"},
            record_index=0,
        )
        assert ctx.agent_config is config

    def test_sets_mode_to_batch(self):
        ctx = BatchContextAdapter.to_processing_context(
            agent_config={},
            original_row={},
            record_index=0,
        )
        assert ctx.mode == ProcessingMode.BATCH

    def test_sets_is_first_stage_false(self):
        ctx = BatchContextAdapter.to_processing_context(
            agent_config={},
            original_row={},
            record_index=0,
        )
        assert ctx.is_first_stage is False

    def test_maps_original_row_as_current_item(self):
        row = {"source_guid": "sg1", "target_id": "tgt1", "lineage": ["node_a"]}
        ctx = BatchContextAdapter.to_processing_context(
            agent_config={},
            original_row=row,
            record_index=0,
        )
        assert ctx.current_item is row

    def test_maps_record_index(self):
        ctx = BatchContextAdapter.to_processing_context(
            agent_config={},
            original_row={},
            record_index=42,
        )
        assert ctx.record_index == 42

    def test_maps_output_directory(self):
        ctx = BatchContextAdapter.to_processing_context(
            agent_config={},
            original_row={},
            record_index=0,
            output_directory="/tmp/output",
        )
        assert ctx.output_directory == "/tmp/output"

    def test_agent_name_from_agent_type(self):
        ctx = BatchContextAdapter.to_processing_context(
            agent_config={"agent_type": "my_agent"},
            original_row={},
            record_index=0,
        )
        assert ctx.agent_name == "my_agent"

    def test_agent_name_defaults_to_unknown(self):
        ctx = BatchContextAdapter.to_processing_context(
            agent_config={},
            original_row={},
            record_index=0,
        )
        assert ctx.agent_name == "unknown_action"


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

    def test_maps_source_guid(self):
        result = BatchContextAdapter.to_processing_result(
            data=[],
            source_guid="sg_abc",
        )
        assert result.source_guid == "sg_abc"

    def test_maps_pre_extracted_metadata(self):
        meta = {"model": "gpt-4", "tokens": 100}
        result = BatchContextAdapter.to_processing_result(
            data=[],
            source_guid="sg1",
            pre_extracted_metadata=meta,
        )
        assert result.pre_extracted_metadata is meta

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

    def test_passthrough_defaults_to_empty(self):
        result = BatchContextAdapter.to_processing_result(
            data=[],
            source_guid="sg1",
        )
        assert result.passthrough_fields == {}

    def test_pre_extracted_metadata_defaults_to_none(self):
        result = BatchContextAdapter.to_processing_result(
            data=[],
            source_guid="sg1",
        )
        assert result.pre_extracted_metadata is None
