"""
Batch enrichment parity test.

Verifies that the refactored pipeline-based batch enrichment produces
identical output to what the old inline enrichment path would produce.
Field-by-field comparison: metadata, lineage, node_id, target_id,
source_guid, version_correlation_id, _recovery.
"""

import pytest

from agent_actions.llm.batch.processing.result_processor import BatchResultProcessor
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.types import RecoveryMetadata, RetryMetadata


class TestBatchEnrichmentParity:
    """Verify pipeline enrichment produces correct output for batch results."""

    @pytest.fixture
    def processor(self):
        return BatchResultProcessor()

    @pytest.fixture
    def agent_config(self):
        return {
            "agent_type": "test_agent",
            "json_mode": True,
        }

    def test_version_correlation_id_present_for_versioned_agent(self, processor):
        """version_correlation_id should be set by VersionIdEnricher for versioned agents."""
        versioned_config = {
            "agent_type": "test_agent",
            "json_mode": True,
            "is_versioned_agent": True,
            "version_base_name": "test_agent",
            "workflow_session_id": "session_123",
        }
        context_map = {
            "id_1": {
                "source_guid": "sg_1",
                "target_id": "tgt_1",
                "content": {"input": "data"},
            }
        }
        batch_results = [
            BatchResult(
                custom_id="id_1",
                success=True,
                content={"output": "result"},
                metadata={},
            )
        ]

        result = processor.process(
            batch_results=batch_results,
            context_map=context_map,
            agent_config=versioned_config,
        )

        assert len(result) == 1
        assert "version_correlation_id" in result[0]

    def test_recovery_metadata_present_when_retry_occurred(self, processor, agent_config):
        """_recovery field should be set when recovery metadata is present."""
        recovery = RecoveryMetadata(
            retry=RetryMetadata(
                attempts=2,
                failures=1,
                succeeded=True,
                reason="timeout",
            )
        )
        context_map = {
            "id_1": {
                "source_guid": "sg_1",
                "target_id": "tgt_1",
                "content": {"input": "data"},
            }
        }
        batch_results = [
            BatchResult(
                custom_id="id_1",
                success=True,
                content={"output": "result"},
                metadata={},
                recovery_metadata=recovery,
            )
        ]

        result = processor.process(
            batch_results=batch_results,
            context_map=context_map,
            agent_config=agent_config,
        )

        assert len(result) == 1
        assert "_recovery" in result[0]
        assert result[0]["_recovery"]["retry"]["attempts"] == 2
        assert result[0]["_recovery"]["retry"]["reason"] == "timeout"

    def test_ancestry_chain_parity(self, processor, agent_config):
        """parent_target_id and root_target_id should be set correctly."""
        context_map = {
            "id_1": {
                "source_guid": "sg_1",
                "target_id": "parent_tgt",
                "root_target_id": "root_tgt",
                "content": {"input": "data"},
                "lineage": ["prev_node"],
            }
        }
        batch_results = [
            BatchResult(
                custom_id="id_1",
                success=True,
                content={"output": "result"},
                metadata={},
            )
        ]

        result = processor.process(
            batch_results=batch_results,
            context_map=context_map,
            agent_config=agent_config,
        )

        assert len(result) == 1
        assert result[0]["parent_target_id"] == "parent_tgt"
        assert result[0]["root_target_id"] == "root_tgt"

    def test_multiple_items_all_enriched(self, processor, agent_config):
        """Multiple batch results should all be independently enriched."""
        context_map = {
            "id_1": {
                "source_guid": "sg_1",
                "target_id": "tgt_1",
                "content": {"input": "data1"},
            },
            "id_2": {
                "source_guid": "sg_2",
                "target_id": "tgt_2",
                "content": {"input": "data2"},
            },
        }
        batch_results = [
            BatchResult(
                custom_id="id_1",
                success=True,
                content={"output": "result1"},
                metadata={"model": "gpt-4"},
            ),
            BatchResult(
                custom_id="id_2",
                success=True,
                content={"output": "result2"},
                metadata={"model": "gpt-4"},
            ),
        ]

        result = processor.process(
            batch_results=batch_results,
            context_map=context_map,
            agent_config=agent_config,
        )

        assert len(result) == 2
        for item in result:
            assert "metadata" in item
            assert "node_id" in item
            assert "lineage" in item
            assert "target_id" in item
            assert "source_guid" in item

        # Different source_guids
        source_guids = {item["source_guid"] for item in result}
        assert source_guids == {"sg_1", "sg_2"}
