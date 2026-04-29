"""
Tests for upstream unprocessed record filtering (#943).

Verifies that records with _unprocessed=True are:
1. Detected by TaskPreparer._is_upstream_unprocessed()
2. Short-circuited in TaskPreparer.prepare() (no context loading, no prompt)
3. Handled as UNPROCESSED in OnlineLLMStrategy.process_record()
4. Counted separately in ResultCollector
5. Enriched with lineage but not LLM metadata
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.config.types import RunMode
from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.utils.correlation import VersionIdGenerator


@pytest.fixture(autouse=True)
def clear_correlation_registry():
    """Clear correlation registry to avoid cross-test pollution."""
    VersionIdGenerator.clear_version_correlation_registry()
    yield
    VersionIdGenerator.clear_version_correlation_registry()


# --- TaskPreparer._is_upstream_unprocessed ---


class TestIsUpstreamUnprocessed:
    """Tests for the _is_upstream_unprocessed static helper."""

    def test_detects_unprocessed(self):
        item = {"content": "stale", "_unprocessed": True}
        assert TaskPreparer._is_upstream_unprocessed(item) is True

    def test_normal_record_passes(self):
        item = {"content": "real", "metadata": {"agent_type": "llm"}}
        assert TaskPreparer._is_upstream_unprocessed(item) is False

    def test_no_metadata_passes(self):
        item = {"content": "raw data"}
        assert TaskPreparer._is_upstream_unprocessed(item) is False

    def test_non_dict_passes(self):
        assert TaskPreparer._is_upstream_unprocessed("plain string") is False

    def test_truthy_non_true_does_not_trigger(self):
        """_unprocessed must be exactly True, not just truthy."""
        item = {"content": "data", "_unprocessed": 1}
        assert TaskPreparer._is_upstream_unprocessed(item) is False

    def test_unprocessed_false_does_not_trigger(self):
        item = {"content": "data", "_unprocessed": False}
        assert TaskPreparer._is_upstream_unprocessed(item) is False


# --- TaskPreparer.prepare() early exit ---


class TestTaskPreparerUpstreamUnprocessed:
    """Tests for TaskPreparer.prepare() early exit on unprocessed records."""

    def _make_context(self):
        return PreparationContext(
            agent_config={"agent_type": "test_action"},
            agent_name="test_action",
            is_first_stage=False,
        )

    def test_returns_upstream_unprocessed_status(self):
        preparer = TaskPreparer()
        item = {
            "content": {"upstream_action": {"data": "stale"}},
            "source_guid": "sg_123",
            "_unprocessed": True,
        }
        result = preparer.prepare(item, self._make_context())

        assert result.guard_status == GuardStatus.UPSTREAM_UNPROCESSED
        assert result.is_upstream_unprocessed is True
        assert result.guard_behavior is None
        assert result.source_guid == "sg_123"
        assert result.original_content == {"upstream_action": {"data": "stale"}}
        assert result.formatted_prompt == ""

    @patch.object(TaskPreparer, "_load_full_context")
    def test_no_context_loading(self, mock_load):
        """Verify _load_full_context is NOT called for unprocessed records."""
        preparer = TaskPreparer()
        item = {
            "content": {"upstream_action": {"val": "stale"}},
            "_unprocessed": True,
        }
        preparer.prepare(item, self._make_context())
        mock_load.assert_not_called()

    def test_preserves_existing_target_id(self):
        preparer = TaskPreparer()
        item = {
            "content": {"upstream_action": {"val": "stale"}},
            "source_guid": "sg_456",
            "_unprocessed": True,
        }
        result = preparer.prepare(item, self._make_context(), existing_target_id="tgt_existing")
        assert result.target_id == "tgt_existing"


# --- OnlineLLMStrategy handles UNPROCESSED ---


class TestOnlineLLMStrategyUnprocessed:
    """Tests for OnlineLLMStrategy handling of UPSTREAM_UNPROCESSED."""

    def test_creates_unprocessed_result(self):
        config = {"agent_type": "test_action"}
        strategy = OnlineLLMStrategy(config, "test_action")
        context = ProcessingContext(
            agent_config=config,
            agent_name="test_action",
            mode=RunMode.ONLINE,
            is_first_stage=False,
        )

        item = {
            "content": {"original": "data"},
            "source_guid": "sg_unproc_1",
            "_unprocessed": True,
        }

        result = strategy.process_record(item, context, skip_guard=False)

        assert result.status == ProcessingStatus.UNPROCESSED
        assert result.executed is False
        assert len(result.data) >= 1


# --- ResultCollector counts UNPROCESSED separately ---


class TestResultCollectorUnprocessed:
    """Tests for ResultCollector counting of UNPROCESSED results."""

    def test_counts_unprocessed_separately(self):
        results = [
            ProcessingResult.success(data=[{"content": "ok"}]),
            ProcessingResult.unprocessed(
                data=[{"content": "stale"}],
                reason="upstream_unprocessed",
            ),
            ProcessingResult.success(data=[{"content": "ok2"}]),
        ]

        output, _ = ResultCollector.collect_results(
            results,
            agent_config={"agent_type": "test"},
            agent_name="test",
            is_first_stage=False,
        )

        # All 3 records should be in output (unprocessed preserved for lineage)
        assert len(output) == 3

    def test_unprocessed_preserved_in_output(self):
        unprocessed_data = {"content": "stale", "source_guid": "sg_1"}
        results = [
            ProcessingResult.unprocessed(
                data=[unprocessed_data],
                reason="upstream_unprocessed",
            ),
        ]

        output, _ = ResultCollector.collect_results(
            results,
            agent_config={"agent_type": "test"},
            agent_name="test",
            is_first_stage=False,
        )

        assert len(output) == 1
        assert output[0]["content"] == "stale"


# --- Enrichment adds lineage to UNPROCESSED ---


class TestEnrichmentUnprocessed:
    """Tests for enrichment pipeline behavior on UNPROCESSED records."""

    def test_lineage_added_to_unprocessed(self):
        config = {"agent_type": "enrich_action"}
        context = ProcessingContext(
            agent_config=config,
            agent_name="enrich_action",
            mode=RunMode.ONLINE,
            is_first_stage=True,
            record_index=0,
        )
        pipeline = EnrichmentPipeline()

        item = {
            "content": {"original": "data"},
            "source_guid": "sg_enrich_1",
            "_unprocessed": True,
        }
        result = ProcessingResult.unprocessed(
            data=[item],
            reason="upstream_unprocessed",
            source_guid="sg_enrich_1",
        )

        enriched = pipeline.enrich(result, context)

        assert len(enriched.data) == 1
        enriched_item = enriched.data[0]
        # LineageEnricher should add node_id and lineage
        assert "node_id" in enriched_item
        assert "lineage" in enriched_item

    def test_metadata_enricher_skips_unprocessed(self):
        """MetadataEnricher skips because executed=False."""
        config = {"agent_type": "meta_action"}
        context = ProcessingContext(
            agent_config=config,
            agent_name="meta_action",
            mode=RunMode.ONLINE,
            is_first_stage=True,
            record_index=0,
        )
        pipeline = EnrichmentPipeline()

        item = {
            "content": {"data": "stale"},
            "source_guid": "sg_meta_1",
        }
        result = ProcessingResult.unprocessed(
            data=[item],
            reason="upstream_unprocessed",
            source_guid="sg_meta_1",
        )

        enriched = pipeline.enrich(result, context)

        enriched_item = enriched.data[0]
        metadata = enriched_item.get("metadata", {})
        # MetadataEnricher should NOT have added agent_type (since executed=False)
        # The original metadata should not have been overwritten with LLM metadata
        assert metadata.get("agent_type") != "llm"


# --- Batch path: reason detection in _stage_6_merge_passthroughs ---


class TestBatchPathReasonDetection:
    """Tests for three-way reason branching in BatchResultStrategy._reconcile_passthroughs."""

    def _make_ctx(self, passthrough_records):
        """Build a minimal BatchProcessingContext with mocked reconciler."""
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchProcessingContext,
        )

        reconciliation = MagicMock()
        reconciliation.passthrough_records = passthrough_records

        reconciler = MagicMock()
        reconciler.reconcile.return_value = reconciliation
        reconciler.get_record_index.return_value = 0
        reconciler.get_source_guid.return_value = "sg_batch_1"

        return BatchProcessingContext(
            batch_results=[],
            context_map={},
            output_directory=None,
            agent_config={"agent_type": "test_batch", "action_name": "test_batch"},
            reconciler=reconciler,
            exhausted_recovery=None,
        )

    def test_upstream_unprocessed_reason(self):
        """Records with FILTER_PHASE=upstream_unprocessed get reason=upstream_unprocessed."""
        from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchResultStrategy,
        )

        row = {
            "content": {"upstream_action": {"field": "value"}},
            "source_guid": "sg_batch_1",
            ContextMetaKeys.FILTER_PHASE: "upstream_unprocessed",
        }
        ctx = self._make_ctx(passthrough_records=[("cid_1", row)])
        processor = BatchResultStrategy()
        results = processor._reconcile_passthroughs(ctx)

        assert len(results) == 1
        item = results[0].data[0]
        assert item["metadata"]["reason"] == "upstream_unprocessed"
        assert item["metadata"]["agent_type"] == "tombstone"
        assert item.get("_unprocessed") is True
        assert item["content"]["test_batch"] is None
        assert item["content"]["upstream_action"] == {"field": "value"}

    def test_guard_skipped_reason(self):
        """Records with SKIPPED filter status get reason=guard_skip."""
        from agent_actions.llm.batch.core.batch_constants import FilterStatus
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchResultStrategy,
        )

        row = {"content": {"prev": {"x": 1}}, "source_guid": "sg_batch_2"}
        BatchContextMetadata.set_filter_status(row, FilterStatus.SKIPPED)
        ctx = self._make_ctx(passthrough_records=[("cid_2", row)])
        processor = BatchResultStrategy()
        results = processor._reconcile_passthroughs(ctx)

        assert len(results) == 1
        item = results[0].data[0]
        assert item["metadata"]["reason"] == "guard_skip"
        assert item["metadata"]["agent_type"] == "tombstone"
        assert item.get("_unprocessed") is True
        assert item["content"]["test_batch"] is None

    def test_batch_not_returned_reason(self):
        """Records without filter metadata get reason=batch_not_returned."""
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchResultStrategy,
        )

        row = {"content": {"prev": {"x": 1}}, "source_guid": "sg_batch_3"}
        ctx = self._make_ctx(passthrough_records=[("cid_3", row)])
        processor = BatchResultStrategy()
        results = processor._reconcile_passthroughs(ctx)

        assert len(results) == 1
        item = results[0].data[0]
        assert item["metadata"]["reason"] == "batch_not_returned"
        assert item["metadata"]["agent_type"] == "tombstone"
        assert item.get("_unprocessed") is True
        assert item["content"]["test_batch"] is None

    def test_upstream_unprocessed_uses_unprocessed_status(self):
        """upstream_unprocessed records should use ProcessingResult.unprocessed(), not .skipped()."""
        from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchResultStrategy,
        )

        row = {
            "content": {"upstream": {"data": "stale"}},
            "source_guid": "sg_batch_4",
            ContextMetaKeys.FILTER_PHASE: "upstream_unprocessed",
        }
        ctx = self._make_ctx(passthrough_records=[("cid_4", row)])
        processor = BatchResultStrategy()

        results = processor._reconcile_passthroughs(ctx)

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.UNPROCESSED
        assert results[0].processing_context is not None

    def test_batch_not_returned_uses_unprocessed_status(self):
        """batch_not_returned records should use ProcessingResult.unprocessed(), not .skipped()."""
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchResultStrategy,
        )

        row = {"content": {"prev": {"x": 1}}, "source_guid": "sg_batch_5"}
        ctx = self._make_ctx(passthrough_records=[("cid_5", row)])
        processor = BatchResultStrategy()

        results = processor._reconcile_passthroughs(ctx)

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.UNPROCESSED
        assert results[0].processing_context is not None
