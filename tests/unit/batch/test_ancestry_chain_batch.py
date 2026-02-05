"""
Test ancestry chain field propagation in batch mode.

Tests for issue #799: Batch mode was missing parent_target_id and root_target_id
fields that are properly set in online mode.

The ancestry chain enables:
- Diamond pattern workflows (fan-out/fan-in)
- Map-reduce aggregation
- Historical data matching
"""

import pytest

from agent_actions.llm.batch.processing.result_processor import BatchResultProcessor
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.exhausted_builder import ExhaustedRecordBuilder
from agent_actions.processing.types import RecoveryMetadata, RetryMetadata


class TestBatchAncestryChainPropagation:
    """Test that batch mode properly sets ancestry chain fields."""

    @pytest.fixture
    def processor(self):
        return BatchResultProcessor()

    @pytest.fixture
    def basic_agent_config(self):
        return {
            "agent_type": "test_agent",
            "json_mode": True,
        }

    def test_successful_result_sets_parent_target_id(self, processor, basic_agent_config):
        """Verify parent_target_id is set from input's target_id."""
        # Input row with target_id
        original_row = {
            "source_guid": "src_123",
            "target_id": "parent_tgt_001",
            "content": {"field": "value"},
            "lineage": ["extract_abc"],
        }

        context_map = {"custom_001": original_row}

        batch_results = [
            BatchResult(
                custom_id="custom_001",
                success=True,
                content={"output": "result"},
                metadata={},
            )
        ]

        result = processor.process(
            batch_results=batch_results,
            context_map=context_map,
            agent_config=basic_agent_config,
        )

        assert len(result) == 1
        assert result[0]["parent_target_id"] == "parent_tgt_001"

    def test_successful_result_sets_root_target_id_from_input(self, processor, basic_agent_config):
        """Verify root_target_id is preserved from input's root_target_id."""
        # Input row with existing root_target_id (from earlier in chain)
        original_row = {
            "source_guid": "src_123",
            "target_id": "parent_tgt_002",
            "root_target_id": "original_root_001",  # From earlier in chain
            "content": {"field": "value"},
            "lineage": ["extract_abc", "transform_def"],
        }

        context_map = {"custom_002": original_row}

        batch_results = [
            BatchResult(
                custom_id="custom_002",
                success=True,
                content={"output": "result"},
                metadata={},
            )
        ]

        result = processor.process(
            batch_results=batch_results,
            context_map=context_map,
            agent_config=basic_agent_config,
        )

        assert len(result) == 1
        assert result[0]["root_target_id"] == "original_root_001"

    def test_successful_result_uses_target_id_as_root_when_no_root(
        self, processor, basic_agent_config
    ):
        """Verify root_target_id defaults to input's target_id when no root exists."""
        # Input row without root_target_id (first stage output)
        original_row = {
            "source_guid": "src_123",
            "target_id": "first_stage_tgt",
            "content": {"field": "value"},
            "lineage": ["extract_abc"],
        }

        context_map = {"custom_003": original_row}

        batch_results = [
            BatchResult(
                custom_id="custom_003",
                success=True,
                content={"output": "result"},
                metadata={},
            )
        ]

        result = processor.process(
            batch_results=batch_results,
            context_map=context_map,
            agent_config=basic_agent_config,
        )

        assert len(result) == 1
        # When input has no root_target_id, input becomes the root
        assert result[0]["root_target_id"] == "first_stage_tgt"

    def test_ancestry_chain_multi_level(self, processor, basic_agent_config):
        """Verify ancestry chain works across multiple levels."""
        # Simulate stage 3 input (already has parent_target_id and root_target_id)
        original_row = {
            "source_guid": "src_stage3",
            "target_id": "stage2_output_tgt",
            "parent_target_id": "stage1_output_tgt",  # Stage 2's parent
            "root_target_id": "original_input_tgt",  # Original root
            "content": {"field": "stage2_value"},
            "lineage": ["stage1_abc", "stage2_def"],
        }

        context_map = {"custom_004": original_row}

        batch_results = [
            BatchResult(
                custom_id="custom_004",
                success=True,
                content={"stage3_output": "result"},
                metadata={},
            )
        ]

        result = processor.process(
            batch_results=batch_results,
            context_map=context_map,
            agent_config=basic_agent_config,
        )

        assert len(result) == 1
        # parent_target_id should be the immediate parent (stage 2)
        assert result[0]["parent_target_id"] == "stage2_output_tgt"
        # root_target_id should be preserved from input
        assert result[0]["root_target_id"] == "original_input_tgt"


class TestExhaustedBuilderAncestryChain:
    """Test that ExhaustedRecordBuilder properly sets ancestry chain fields."""

    def test_exhausted_item_sets_parent_target_id(self):
        """Verify exhausted item has parent_target_id from input."""
        original_row = {
            "source_guid": "src_exhausted",
            "target_id": "parent_tgt_exhausted",
            "content": {"field": "value"},
            "lineage": ["extract_abc"],
        }

        recovery_metadata = RecoveryMetadata(
            retry=RetryMetadata(
                attempts=3,
                failures=3,
                succeeded=False,
                reason="api_error",
            ),
        )

        result = ExhaustedRecordBuilder.build_exhausted_item(
            source_guid="src_exhausted",
            original_row=original_row,
            recovery_metadata=recovery_metadata,
            agent_config={"agent_type": "test_agent"},
            action_name="test_agent",
        )

        assert result["parent_target_id"] == "parent_tgt_exhausted"

    def test_exhausted_item_preserves_root_target_id(self):
        """Verify exhausted item preserves root_target_id from input."""
        original_row = {
            "source_guid": "src_exhausted",
            "target_id": "parent_tgt",
            "root_target_id": "original_root",
            "content": {"field": "value"},
        }

        recovery_metadata = RecoveryMetadata(
            retry=RetryMetadata(
                attempts=3,
                failures=3,
                succeeded=False,
                reason="api_error",
            ),
        )

        result = ExhaustedRecordBuilder.build_exhausted_item(
            source_guid="src_exhausted",
            original_row=original_row,
            recovery_metadata=recovery_metadata,
            agent_config={},
            action_name="test_agent",
        )

        assert result["root_target_id"] == "original_root"

    def test_exhausted_item_uses_target_as_root_when_no_root(self):
        """Verify exhausted item uses target_id as root when no root exists."""
        original_row = {
            "source_guid": "src_exhausted",
            "target_id": "first_stage_tgt",
            "content": {"field": "value"},
        }

        recovery_metadata = RecoveryMetadata(
            retry=RetryMetadata(
                attempts=3,
                failures=3,
                succeeded=False,
                reason="api_error",
            ),
        )

        result = ExhaustedRecordBuilder.build_exhausted_item(
            source_guid="src_exhausted",
            original_row=original_row,
            recovery_metadata=recovery_metadata,
            agent_config={},
            action_name="test_agent",
        )

        # When input has no root_target_id, input becomes the root
        assert result["root_target_id"] == "first_stage_tgt"

    def test_exhausted_item_without_target_id(self):
        """Verify behavior when original_row has no target_id - no ancestry fields set."""
        original_row = {
            "source_guid": "src_no_target",
            "content": {"field": "value"},
            # No target_id - edge case
        }

        recovery_metadata = RecoveryMetadata(
            retry=RetryMetadata(
                attempts=3,
                failures=3,
                succeeded=False,
                reason="api_error",
            ),
        )

        result = ExhaustedRecordBuilder.build_exhausted_item(
            source_guid="src_no_target",
            original_row=original_row,
            recovery_metadata=recovery_metadata,
            agent_config={},
            action_name="test_agent",
        )

        # When input has no target_id, ancestry fields should NOT be set
        # This documents expected behavior - ancestry requires target_id
        assert "parent_target_id" not in result
        assert "root_target_id" not in result
        # But other fields should still be present
        assert result["source_guid"] == "src_no_target"
        assert "lineage" in result


class TestAncestryChainParityVerification:
    """Verification tests that batch mode matches online mode behavior."""

    def test_batch_delegates_enrichment_to_pipeline(self):
        """Verify batch result processor delegates enrichment to EnrichmentPipeline."""
        from agent_actions.llm.batch.processing.result_processor import (
            BatchResultProcessor,
        )

        processor = BatchResultProcessor()

        # Pipeline should be set up with default enrichers including LineageEnricher
        from agent_actions.processing.enrichment import LineageEnricher

        enricher_types = [type(e) for e in processor._enrichment_pipeline.enrichers]
        assert LineageEnricher in enricher_types, (
            "BatchResultProcessor should use EnrichmentPipeline with LineageEnricher"
        )

    def test_exhausted_builder_ancestry_behavioral(self):
        """Behavioral test: exhausted item gets parent_target_id from input's target_id.

        This replaces the brittle inspect.getsource test with actual behavior verification.
        """
        # Input with both target_id and parent_target_id (multi-level chain)
        original_row = {
            "source_guid": "src_test",
            "target_id": "my_target_id",
            "parent_target_id": "grandparent_target_id",  # Should NOT be copied
            "content": {"field": "value"},
        }

        recovery_metadata = RecoveryMetadata(
            retry=RetryMetadata(
                attempts=3,
                failures=3,
                succeeded=False,
                reason="api_error",
            ),
        )

        result = ExhaustedRecordBuilder.build_exhausted_item(
            source_guid="src_test",
            original_row=original_row,
            recovery_metadata=recovery_metadata,
            agent_config={},
            action_name="test_agent",
        )

        # Key assertion: parent_target_id should be input's target_id
        # NOT input's parent_target_id (which would be incorrect)
        assert result["parent_target_id"] == "my_target_id"
        assert result["parent_target_id"] != "grandparent_target_id"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
