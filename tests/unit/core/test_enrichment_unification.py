"""
Tests verifying that ALL non-FILTERED record paths produce enriched output.

Bug #935: SKIPPED, EXHAUSTED, and batch passthrough records were bypassing
the EnrichmentPipeline, causing missing version_correlation_id, lineage,
and metadata. These tests verify the fix.
"""

import pytest

from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingMode,
    ProcessingResult,
    RecoveryMetadata,
    RetryMetadata,
)
from agent_actions.utils.correlation import VersionIdGenerator


@pytest.fixture(autouse=True)
def clear_correlation_registry():
    """Clear the correlation registry before each test to avoid cross-test pollution."""
    VersionIdGenerator.clear_version_correlation_registry()
    yield
    VersionIdGenerator.clear_version_correlation_registry()


def _make_versioned_config(agent_type="test_action"):
    return {
        "agent_type": agent_type,
        "is_versioned_agent": True,
        "version_base_name": agent_type,
        "workflow_session_id": "workflow_test123",
    }


def _make_context(agent_config, record_index=0, is_first_stage=True, current_item=None):
    return ProcessingContext(
        agent_config=agent_config,
        agent_name=agent_config.get("agent_type", "test"),
        mode=ProcessingMode.ONLINE,
        is_first_stage=is_first_stage,
        record_index=record_index,
        current_item=current_item,
    )


class TestOnlineSkippedEnrichment:
    """Verify online SKIPPED results get full enrichment."""

    def test_skipped_has_lineage_and_node_id(self):
        """SKIPPED records should have node_id and lineage from LineageEnricher."""
        config = {"agent_type": "skip_action"}
        context = _make_context(config)
        pipeline = EnrichmentPipeline()

        passthrough_item = {
            "content": {"original": "data"},
            "source_guid": "sg_skip_1",
            "metadata": {"reason": "guard_skip"},
        }
        result = ProcessingResult.skipped(
            passthrough_data=passthrough_item,
            reason="guard_skip",
            source_guid="sg_skip_1",
        )

        enriched = pipeline.enrich(result, context)

        assert len(enriched.data) == 1
        item = enriched.data[0]
        assert "node_id" in item
        assert "lineage" in item
        assert len(item["lineage"]) >= 1

    def test_skipped_has_version_correlation_id(self):
        """SKIPPED records should get version_correlation_id for versioned agents."""
        config = _make_versioned_config()
        context = _make_context(config, record_index=3)
        pipeline = EnrichmentPipeline()

        passthrough_item = {
            "content": {"original": "data"},
            "source_guid": "sg_skip_2",
            "metadata": {"reason": "guard_skip"},
        }
        result = ProcessingResult.skipped(
            passthrough_data=passthrough_item,
            reason="guard_skip",
            source_guid="sg_skip_2",
        )

        enriched = pipeline.enrich(result, context)

        assert len(enriched.data) == 1
        item = enriched.data[0]
        assert "version_correlation_id" in item
        assert item["version_correlation_id"].startswith("corr_")


class TestOnlineExhaustedEnrichment:
    """Verify online EXHAUSTED results get full enrichment."""

    def _make_exhausted_result(self, source_guid="sg_ex_1", content=None, target_id=None):
        item = {
            "content": content or {},
            "source_guid": source_guid,
            "metadata": {"retry_exhausted": True},
        }
        if target_id:
            item["target_id"] = target_id
        result = ProcessingResult.exhausted(
            error="Retry exhausted after 3 attempts",
            source_guid=source_guid,
            recovery_metadata=RecoveryMetadata(
                retry=RetryMetadata(attempts=3, failures=3, succeeded=False, reason="timeout")
            ),
        )
        result.data = [item]
        return result

    def test_exhausted_has_lineage_and_node_id(self):
        """EXHAUSTED records should have node_id and lineage."""
        config = {"agent_type": "exhaust_action"}
        context = _make_context(config)
        pipeline = EnrichmentPipeline()

        result = self._make_exhausted_result()
        enriched = pipeline.enrich(result, context)

        assert len(enriched.data) == 1
        item = enriched.data[0]
        assert "node_id" in item
        assert "lineage" in item

    def test_exhausted_has_version_correlation_id(self):
        """EXHAUSTED records should get version_correlation_id for versioned agents."""
        config = _make_versioned_config("exhaust_action")
        context = _make_context(config, record_index=5)
        pipeline = EnrichmentPipeline()

        result = self._make_exhausted_result()
        enriched = pipeline.enrich(result, context)

        assert len(enriched.data) == 1
        item = enriched.data[0]
        assert "version_correlation_id" in item
        assert item["version_correlation_id"].startswith("corr_")

    def test_exhausted_has_recovery_metadata(self):
        """EXHAUSTED records should have _recovery field from RecoveryEnricher."""
        config = {"agent_type": "exhaust_action"}
        context = _make_context(config)
        pipeline = EnrichmentPipeline()

        result = self._make_exhausted_result()
        enriched = pipeline.enrich(result, context)

        assert len(enriched.data) == 1
        item = enriched.data[0]
        assert "_recovery" in item
        assert item["_recovery"]["retry"]["attempts"] == 3

    def test_exhausted_with_parent_lineage(self):
        """EXHAUSTED downstream records should chain lineage from parent."""
        config = {"agent_type": "downstream_exhaust"}
        parent_item = {
            "source_guid": "sg_parent",
            "target_id": "tgt_parent",
            "lineage": ["prev_node"],
            "node_id": "prev_node",
        }
        context = _make_context(config, is_first_stage=False, current_item=parent_item)
        pipeline = EnrichmentPipeline()

        result = self._make_exhausted_result(source_guid="sg_parent", target_id="tgt_parent")
        enriched = pipeline.enrich(result, context)

        item = enriched.data[0]
        assert "lineage" in item
        # Should include previous lineage plus current node
        assert len(item["lineage"]) >= 2
        assert item["lineage"][0] == "prev_node"


class TestDeterministicSessionId:
    """Verify deterministic session ID produces consistent correlation IDs."""

    def test_same_config_produces_same_correlation_id(self):
        """Same workflow config should produce identical correlation IDs across 'restarts'."""
        config = _make_versioned_config()
        pipeline = EnrichmentPipeline()

        # First "run"
        context1 = _make_context(config, record_index=0)
        item1 = {
            "content": {"data": "test"},
            "source_guid": "sg_det_1",
            "metadata": {},
        }
        result1 = ProcessingResult.skipped(
            passthrough_data=item1, reason="guard_skip", source_guid="sg_det_1"
        )
        enriched1 = pipeline.enrich(result1, context1)
        corr_id_1 = enriched1.data[0]["version_correlation_id"]

        # Clear and "restart" with same config
        VersionIdGenerator.clear_version_correlation_registry()

        context2 = _make_context(config, record_index=0)
        item2 = {
            "content": {"data": "test"},
            "source_guid": "sg_det_1",
            "metadata": {},
        }
        result2 = ProcessingResult.skipped(
            passthrough_data=item2, reason="guard_skip", source_guid="sg_det_1"
        )
        enriched2 = pipeline.enrich(result2, context2)
        corr_id_2 = enriched2.data[0]["version_correlation_id"]

        # Same config + same position = same correlation ID
        assert corr_id_1 == corr_id_2

    def test_different_session_produces_different_correlation_id(self):
        """Different workflow_session_id should produce different correlation IDs."""
        pipeline = EnrichmentPipeline()

        config_a = _make_versioned_config()
        config_a["workflow_session_id"] = "workflow_aaa"
        context_a = _make_context(config_a, record_index=0)
        item_a = {
            "content": {"data": "test"},
            "source_guid": "sg_diff_1",
            "metadata": {},
        }
        result_a = ProcessingResult.skipped(
            passthrough_data=item_a, reason="guard_skip", source_guid="sg_diff_1"
        )
        enriched_a = pipeline.enrich(result_a, context_a)

        VersionIdGenerator.clear_version_correlation_registry()

        config_b = _make_versioned_config()
        config_b["workflow_session_id"] = "workflow_bbb"
        context_b = _make_context(config_b, record_index=0)
        item_b = {
            "content": {"data": "test"},
            "source_guid": "sg_diff_1",
            "metadata": {},
        }
        result_b = ProcessingResult.skipped(
            passthrough_data=item_b, reason="guard_skip", source_guid="sg_diff_1"
        )
        enriched_b = pipeline.enrich(result_b, context_b)

        assert (
            enriched_a.data[0]["version_correlation_id"]
            != enriched_b.data[0]["version_correlation_id"]
        )
