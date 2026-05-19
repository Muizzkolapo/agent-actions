"""Phase 8b: UnifiedProcessor retrieve — batch flows through shared pipeline.

TDD tests verifying:
1. BatchResultStrategy satisfies ProcessingStrategy protocol
2. UnifiedProcessor.enrich_and_collect() handles batch results
3. FAILED results with pre-existing data are preserved by collector
4. Batch retrieve produces CollectionStats
"""

from typing import Any, cast

from agent_actions.config.types import ActionConfigDict, RunMode
from agent_actions.processing.record_helpers import build_tombstone
from agent_actions.processing.result_collector import (
    CollectionStats,
    collect_results_from_processing_results,
)
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
)
from agent_actions.record.reasons import (
    BATCH_NOT_RETURNED,
    PREP_FAILED,
)
from agent_actions.record.state import RecordState

ACTION_NAME = "test_batch_action"


def _batch_agent_config(**overrides: Any) -> dict[str, Any]:
    """Minimal batch agent_config."""
    config: dict[str, Any] = {
        "action_name": ACTION_NAME,
        "agent_type": ACTION_NAME,
        "json_mode": True,
        "output_field": "raw_response",
    }
    config.update(overrides)
    return config


def _make_batch_context(
    agent_config: dict[str, Any] | None = None,
    storage_backend: Any = None,
) -> ProcessingContext:
    """Build a batch ProcessingContext."""
    config = agent_config or _batch_agent_config()
    return ProcessingContext(
        agent_config=cast(ActionConfigDict, config),
        agent_name=config.get("action_name", ACTION_NAME),
        mode=RunMode.BATCH,
        storage_backend=storage_backend,
    )


def _make_success_result(source_guid: str = "sg-001", record_index: int = 0) -> ProcessingResult:
    """SUCCESS result carrying per-result processing_context (batch style)."""
    result = ProcessingResult.success(
        data=[
            {
                "target_id": f"t-{source_guid}",
                "source_guid": source_guid,
                "content": {ACTION_NAME: {"field": "value"}},
            }
        ],
        source_guid=source_guid,
    )
    result.processing_context = ProcessingContext(
        agent_config=cast(ActionConfigDict, _batch_agent_config()),
        agent_name=ACTION_NAME,
        mode=RunMode.BATCH,
        record_index=record_index,
    )
    return result


def _make_failed_error_result(source_guid: str = "sg-002") -> ProcessingResult:
    """FAILED result from batch error (processing_context=None, data=[error_item]).

    This is the batch-specific shape from BatchResultStrategy._build_error_result().
    Error results carry data with error info and must NOT be enriched.
    """
    error_item: dict[str, Any] = {
        "source_guid": source_guid,
        "error": "LLM provider timeout",
        "metadata": {"batch_id": "b-123"},
    }
    result = ProcessingResult.failed(
        error="LLM provider timeout",
        source_guid=source_guid,
    )
    result.data = [error_item]
    result.processing_context = None  # Error results skip enrichment
    return result


def _make_failed_passthrough_result(
    source_guid: str = "sg-003", record_index: int = 0
) -> ProcessingResult:
    """FAILED result from batch prep failure (has processing_context + tombstone)."""
    tombstone = build_tombstone(
        ACTION_NAME,
        {"target_id": f"t-{source_guid}", "source_guid": source_guid},
        PREP_FAILED,
        source_guid=source_guid,
    )
    result = ProcessingResult.failed(
        error=PREP_FAILED,
        source_guid=source_guid,
    )
    result.data = [tombstone]
    result.processing_context = ProcessingContext(
        agent_config=cast(ActionConfigDict, _batch_agent_config()),
        agent_name=ACTION_NAME,
        mode=RunMode.BATCH,
        record_index=record_index,
    )
    return result


def _make_exhausted_result(source_guid: str = "sg-004", record_index: int = 0) -> ProcessingResult:
    """EXHAUSTED result with processing_context."""
    result = ProcessingResult.exhausted(
        error="max retries exceeded",
        data=[
            {
                "target_id": f"t-{source_guid}",
                "source_guid": source_guid,
                "content": {ACTION_NAME: {"field": "partial"}},
                "metadata": {"retry_exhausted": True},
            }
        ],
        source_guid=source_guid,
    )
    result.processing_context = ProcessingContext(
        agent_config=cast(ActionConfigDict, _batch_agent_config()),
        agent_name=ACTION_NAME,
        mode=RunMode.BATCH,
        record_index=record_index,
    )
    return result


def _make_unprocessed_result(
    source_guid: str = "sg-005", record_index: int = 0
) -> ProcessingResult:
    """UNPROCESSED result (batch not returned)."""
    tombstone = build_tombstone(
        ACTION_NAME,
        {"target_id": f"t-{source_guid}", "source_guid": source_guid},
        BATCH_NOT_RETURNED,
        source_guid=source_guid,
    )
    result = ProcessingResult.unprocessed(
        data=[tombstone],
        reason=BATCH_NOT_RETURNED,
        source_guid=source_guid,
    )
    result.processing_context = ProcessingContext(
        agent_config=cast(ActionConfigDict, _batch_agent_config()),
        agent_name=ACTION_NAME,
        mode=RunMode.BATCH,
        record_index=record_index,
    )
    return result


# ---------------------------------------------------------------------------
# 1. ProcessingStrategy protocol compliance
# ---------------------------------------------------------------------------


class TestBatchResultStrategyProtocol:
    """BatchResultStrategy must satisfy ProcessingStrategy protocol."""

    def test_satisfies_processing_strategy_protocol(self):
        """BatchResultStrategy must be recognized as a ProcessingStrategy."""
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchResultStrategy,
        )
        from agent_actions.processing.unified import ProcessingStrategy

        strategy = BatchResultStrategy()
        assert isinstance(strategy, ProcessingStrategy)

    def test_invoke_method_exists(self):
        """BatchResultStrategy must have an invoke() method."""
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchResultStrategy,
        )

        strategy = BatchResultStrategy()
        assert hasattr(strategy, "invoke")
        assert callable(strategy.invoke)


# ---------------------------------------------------------------------------
# 2. UnifiedProcessor.enrich_and_collect
# ---------------------------------------------------------------------------


class TestUnifiedProcessorEnrichAndCollect:
    """UnifiedProcessor must expose enrich_and_collect for batch retrieve."""

    def test_enrich_and_collect_exists(self):
        """enrich_and_collect method must exist on UnifiedProcessor."""
        from agent_actions.processing.unified import UnifiedProcessor

        processor = UnifiedProcessor()
        assert hasattr(processor, "enrich_and_collect")
        assert callable(processor.enrich_and_collect)

    def test_returns_output_and_stats(self):
        """enrich_and_collect returns (output_records, CollectionStats)."""
        from agent_actions.processing.unified import UnifiedProcessor

        processor = UnifiedProcessor()
        ctx = _make_batch_context()
        results = [_make_success_result("sg-001")]

        output, stats = processor.enrich_and_collect(results, ctx)

        assert isinstance(output, list)
        assert isinstance(stats, CollectionStats)

    def test_success_result_stamped_processed(self):
        """SUCCESS results get _state=PROCESSED."""
        from agent_actions.processing.unified import UnifiedProcessor

        processor = UnifiedProcessor()
        ctx = _make_batch_context()
        results = [_make_success_result("sg-001")]

        output, stats = processor.enrich_and_collect(results, ctx)

        assert len(output) == 1
        assert output[0]["_state"] == RecordState.PROCESSED.value
        assert stats.success == 1

    def test_mixed_batch_results(self):
        """Mixed batch results produce correct CollectionStats."""
        from agent_actions.processing.unified import UnifiedProcessor

        processor = UnifiedProcessor()
        ctx = _make_batch_context()
        results = [
            _make_success_result("sg-001", record_index=0),
            _make_success_result("sg-002", record_index=1),
            _make_failed_error_result("sg-003"),
            _make_exhausted_result("sg-004", record_index=3),
            _make_unprocessed_result("sg-005", record_index=4),
        ]

        output, stats = processor.enrich_and_collect(results, ctx)

        assert stats.success == 2
        assert stats.failed == 1
        assert stats.exhausted == 1
        assert stats.unprocessed == 1
        assert len(output) == 5


# ---------------------------------------------------------------------------
# 3. FAILED result data preservation
# ---------------------------------------------------------------------------


class TestFailedResultDataPreservation:
    """Collector must preserve pre-existing data on FAILED results."""

    def test_failed_with_data_preserves_error_item(self):
        """FAILED results with data=[error_item] preserve the error item."""
        result = _make_failed_error_result("sg-002")
        assert len(result.data) == 1
        assert result.data[0]["error"] == "LLM provider timeout"

        records, stats = collect_results_from_processing_results([result], ACTION_NAME)

        assert stats.failed == 1
        assert len(records) == 1
        # Error item must be preserved, not replaced by a fresh tombstone
        assert records[0].get("error") == "LLM provider timeout"

    def test_failed_without_data_builds_tombstone(self):
        """FAILED results with data=[] still build a tombstone (online path)."""
        result = ProcessingResult.failed(
            error="some error",
            source_guid="sg-010",
            input_record={"source_guid": "sg-010", "target_id": "t-010"},
        )
        assert result.data == []

        records, stats = collect_results_from_processing_results([result], ACTION_NAME)

        assert stats.failed == 1
        assert len(records) == 1
        # Tombstone built by collector
        assert records[0].get("metadata", {}).get("agent_type") == "tombstone"

    def test_failed_passthrough_with_tombstone_preserved(self):
        """FAILED results from batch prep carry build_tombstone output — preserved."""
        result = _make_failed_passthrough_result("sg-003")
        assert len(result.data) == 1

        records, stats = collect_results_from_processing_results([result], ACTION_NAME)

        assert stats.failed == 1
        assert len(records) == 1
        # Tombstone from build_tombstone must be preserved
        assert records[0].get("metadata", {}).get("reason") == PREP_FAILED


# ---------------------------------------------------------------------------
# 4. Enrichment uses per-result processing_context
# ---------------------------------------------------------------------------


class TestPerResultEnrichmentContext:
    """UnifiedProcessor._enrich must use per-result processing_context when set."""

    def test_enrichment_uses_per_result_context(self):
        """Results with processing_context use their own context for enrichment."""
        from agent_actions.processing.unified import UnifiedProcessor

        processor = UnifiedProcessor()
        ctx = _make_batch_context()

        # Two results at different record_index values
        r1 = _make_success_result("sg-001", record_index=0)
        r2 = _make_success_result("sg-002", record_index=1)

        output, stats = processor.enrich_and_collect([r1, r2], ctx)

        assert stats.success == 2
        assert len(output) == 2
        # Both records should have _state stamped
        assert all(r["_state"] == RecordState.PROCESSED.value for r in output)

    def test_error_results_skip_enrichment(self):
        """Batch error results (processing_context=None) skip enrichment."""
        from agent_actions.processing.unified import UnifiedProcessor

        processor = UnifiedProcessor()
        ctx = _make_batch_context()

        error_result = _make_failed_error_result("sg-003")
        assert error_result.processing_context is None

        output, stats = processor.enrich_and_collect([error_result], ctx)

        assert stats.failed == 1
        assert len(output) == 1
        # Error item should not have enrichment artifacts (no _lineage, no version_correlation_id)
        record = output[0]
        assert record.get("error") == "LLM provider timeout"


# ---------------------------------------------------------------------------
# 5. CollectionStats parity: online vs batch
# ---------------------------------------------------------------------------


class TestCollectionStatsParity:
    """Online and batch produce equivalent CollectionStats for same result mix."""

    def test_equivalent_stats_for_same_input(self):
        """Same ProcessingResult mix produces identical stats regardless of path."""
        online_results = [
            ProcessingResult.success(
                data=[{"source_guid": "sg-001", "content": {"ns": {"f": "v"}}}],
                source_guid="sg-001",
            ),
            ProcessingResult.failed(
                error="err",
                source_guid="sg-002",
                input_record={"source_guid": "sg-002"},
            ),
            ProcessingResult.exhausted(
                error="max",
                data=[{"source_guid": "sg-003", "content": {"ns": {"f": "p"}}}],
                source_guid="sg-003",
            ),
        ]

        batch_results = [
            ProcessingResult.success(
                data=[{"source_guid": "sg-001", "content": {"ns": {"f": "v"}}}],
                source_guid="sg-001",
            ),
            ProcessingResult.failed(
                error="err",
                source_guid="sg-002",
                input_record={"source_guid": "sg-002"},
            ),
            ProcessingResult.exhausted(
                error="max",
                data=[{"source_guid": "sg-003", "content": {"ns": {"f": "p"}}}],
                source_guid="sg-003",
            ),
        ]

        _, online_stats = collect_results_from_processing_results(
            online_results,
            ACTION_NAME,
            agent_config=_batch_agent_config(),
        )
        _, batch_stats = collect_results_from_processing_results(
            batch_results,
            ACTION_NAME,
            agent_config=None,
        )

        assert online_stats.success == batch_stats.success
        assert online_stats.failed == batch_stats.failed
        assert online_stats.exhausted == batch_stats.exhausted
        assert online_stats.skipped == batch_stats.skipped
        assert online_stats.filtered == batch_stats.filtered
