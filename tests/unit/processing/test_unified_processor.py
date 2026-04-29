"""Tests for UnifiedProcessor skeleton and ProcessingStrategy protocol."""

from typing import Any
from unittest.mock import patch

from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.processing.unified import (
    NoOpStrategy,
    ProcessingStrategy,
    UnifiedProcessor,
)


def _make_context(
    agent_name: str = "test_action",
    *,
    guard: dict | None = None,
    is_first_stage: bool = False,
) -> ProcessingContext:
    """Create a minimal ProcessingContext for testing."""
    config: dict[str, Any] = {
        "agent_type": agent_name,
        "name": agent_name,
    }
    if guard is not None:
        config["guard"] = guard
    return ProcessingContext(
        agent_config=config,
        agent_name=agent_name,
        is_first_stage=is_first_stage,
    )


def _make_record(source_guid: str = "sg-1", **content: Any) -> dict[str, Any]:
    """Create a minimal record dict."""
    return {
        "source_guid": source_guid,
        "content": {**content} if content else {"source": {"field": "value"}},
    }


# ---------------------------------------------------------------------------
# NoOpStrategy
# ---------------------------------------------------------------------------


class TestNoOpStrategy:
    """Tests for the NoOpStrategy pass-through implementation."""

    def test_conforms_to_protocol(self):
        assert isinstance(NoOpStrategy(), ProcessingStrategy)

    def test_returns_one_success_per_record(self):
        strategy = NoOpStrategy()
        records = [_make_record("sg-1"), _make_record("sg-2")]
        context = _make_context()

        results = strategy.invoke(records, context)

        assert len(results) == 2
        assert all(r.status == ProcessingStatus.SUCCESS for r in results)

    def test_preserves_record_data(self):
        strategy = NoOpStrategy()
        record = _make_record("sg-1", source={"x": 42})
        context = _make_context()

        results = strategy.invoke([record], context)

        assert results[0].data == [record]

    def test_preserves_source_guid(self):
        strategy = NoOpStrategy()
        record = _make_record("my-guid")
        context = _make_context()

        results = strategy.invoke([record], context)

        assert results[0].source_guid == "my-guid"

    def test_empty_input_returns_empty(self):
        strategy = NoOpStrategy()
        context = _make_context()

        results = strategy.invoke([], context)

        assert results == []

    def test_record_without_source_guid(self):
        strategy = NoOpStrategy()
        record = {"content": {"source": {"val": 1}}}
        context = _make_context()

        results = strategy.invoke([record], context)

        assert results[0].source_guid is None
        assert results[0].data == [record]


# ---------------------------------------------------------------------------
# UnifiedProcessor — no guard configured
# ---------------------------------------------------------------------------


class TestUnifiedProcessorNoGuard:
    """Tests for UnifiedProcessor when no guard is configured."""

    def test_all_records_pass_through_to_strategy(self):
        processor = UnifiedProcessor()
        strategy = NoOpStrategy()
        records = [_make_record("sg-1"), _make_record("sg-2"), _make_record("sg-3")]
        context = _make_context()

        output, stats = processor.process(records, context, strategy)

        assert stats.success == 3
        assert stats.skipped == 0
        assert stats.filtered == 0

    def test_output_contains_record_data(self):
        processor = UnifiedProcessor()
        strategy = NoOpStrategy()
        record = _make_record("sg-1", source={"key": "val"})
        context = _make_context()

        output, _stats = processor.process([record], context, strategy)

        assert len(output) == 1
        assert output[0]["content"]["source"] == {"key": "val"}

    def test_empty_input_produces_empty_output(self):
        processor = UnifiedProcessor()
        strategy = NoOpStrategy()
        context = _make_context()

        output, stats = processor.process([], context, strategy)

        assert output == []
        assert stats.success == 0

    def test_strategy_not_invoked_when_all_filtered(self):
        """When guard filters everything, strategy.invoke is never called."""

        class TrackingStrategy:
            def __init__(self):
                self.called = False

            def invoke(self, records, context):
                self.called = True
                return []

        processor = UnifiedProcessor()
        tracking = TrackingStrategy()
        context = _make_context(guard={"clause": "item.impossible == true", "behavior": "filter"})
        records = [_make_record("sg-1")]

        # Guard will filter all records
        with patch(
            "agent_actions.processing.unified.prefilter_by_guard",
            return_value=([], [], []),
        ):
            processor.process(records, context, tracking)

        assert not tracking.called


# ---------------------------------------------------------------------------
# UnifiedProcessor — guard filtering
# ---------------------------------------------------------------------------


class TestUnifiedProcessorGuardFilter:
    """Tests for guard filtering behavior in UnifiedProcessor."""

    def test_skipped_records_produce_tombstones(self):
        processor = UnifiedProcessor()
        strategy = NoOpStrategy()
        context = _make_context(guard={"clause": "item.flag == true", "behavior": "skip"})

        skipped_record = _make_record("sg-skip")

        with patch(
            "agent_actions.processing.unified.prefilter_by_guard",
            return_value=([], [skipped_record], []),
        ):
            output, stats = processor.process([skipped_record], context, strategy)

        assert stats.skipped == 1
        assert stats.success == 0

    def test_filtered_records_excluded_from_output(self):
        processor = UnifiedProcessor()
        strategy = NoOpStrategy()
        context = _make_context(guard={"clause": "item.flag == true", "behavior": "filter"})

        record = _make_record("sg-filter")

        with patch(
            "agent_actions.processing.unified.prefilter_by_guard",
            return_value=([], [], []),
        ):
            output, stats = processor.process([record], context, strategy)

        assert stats.filtered == 1
        assert stats.success == 0

    def test_mixed_guard_outcomes(self):
        """Some records pass, some skip, some filter."""
        processor = UnifiedProcessor()
        strategy = NoOpStrategy()
        context = _make_context(guard={"clause": "item.x > 0", "behavior": "skip"})

        passing = _make_record("sg-pass")
        skipped = _make_record("sg-skip")
        # 3 total records: 1 passes, 1 skipped, 1 filtered
        all_records = [passing, skipped, _make_record("sg-filter")]

        with patch(
            "agent_actions.processing.unified.prefilter_by_guard",
            return_value=([passing], [skipped], [passing]),
        ):
            output, stats = processor.process(all_records, context, strategy)

        assert stats.success == 1
        assert stats.skipped == 1
        assert stats.filtered == 1


# ---------------------------------------------------------------------------
# UnifiedProcessor — enrichment
# ---------------------------------------------------------------------------


class TestUnifiedProcessorEnrichment:
    """Tests for the enrichment step in UnifiedProcessor."""

    def test_enrichment_pipeline_is_applied(self):
        """Verify enrichment is called for every result."""
        from agent_actions.processing.enrichment import Enricher, EnrichmentPipeline

        class CountingEnricher(Enricher):
            def __init__(self):
                self.count = 0

            def enrich(self, result, context):
                self.count += 1
                return result

        enricher = CountingEnricher()
        pipeline = EnrichmentPipeline(enrichers=[enricher])
        processor = UnifiedProcessor(enrichment_pipeline=pipeline)
        strategy = NoOpStrategy()
        records = [_make_record("sg-1"), _make_record("sg-2")]
        context = _make_context()

        processor.process(records, context, strategy)

        assert enricher.count == 2

    def test_custom_enrichment_pipeline_used(self):
        """A custom pipeline replaces the default one."""
        from agent_actions.processing.enrichment import Enricher, EnrichmentPipeline

        class TagEnricher(Enricher):
            def enrich(self, result, context):
                for item in result.data:
                    item["_tagged"] = True
                return result

        pipeline = EnrichmentPipeline(enrichers=[TagEnricher()])
        processor = UnifiedProcessor(enrichment_pipeline=pipeline)
        strategy = NoOpStrategy()
        records = [_make_record("sg-1")]
        context = _make_context()

        output, _stats = processor.process(records, context, strategy)

        assert output[0].get("_tagged") is True

    def test_enrich_passes_cumulative_record_index_per_result(self):
        """Staff review: enumerate(results) collides when each result has many rows."""

        from agent_actions.processing.enrichment import Enricher, EnrichmentPipeline

        class CaptureIndexEnricher(Enricher):
            def __init__(self) -> None:
                self.seen: list[int] = []

            def enrich(self, result, context):
                self.seen.append(context.record_index)
                return result

        capture = CaptureIndexEnricher()
        pipeline = EnrichmentPipeline(enrichers=[capture])
        processor = UnifiedProcessor(enrichment_pipeline=pipeline)

        class MultiResultStrategy:
            def invoke(self, records, context):
                return [
                    ProcessingResult.success(
                        data=[{"k": 1}, {"k": 2}, {"k": 3}],
                        source_guid="sg-a",
                    ),
                    ProcessingResult.success(
                        data=[{"k": 4}, {"k": 5}],
                        source_guid="sg-b",
                    ),
                ]

        context = _make_context()
        context.record_index = 10
        processor.process([_make_record("sg-1")], context, MultiResultStrategy())

        assert capture.seen == [10, 13]


# ---------------------------------------------------------------------------
# UnifiedProcessor — result collection
# ---------------------------------------------------------------------------


class TestUnifiedProcessorCollection:
    """Tests for the result collection step."""

    def test_stats_reflect_strategy_outcomes(self):
        """Stats accurately count success/failed/exhausted from strategy."""

        class MixedStrategy:
            def invoke(self, records, context):
                return [
                    ProcessingResult.success(data=[records[0]], source_guid="sg-1"),
                    ProcessingResult.failed(error="boom", source_guid="sg-2"),
                ]

        processor = UnifiedProcessor()
        records = [_make_record("sg-1"), _make_record("sg-2")]
        context = _make_context()

        _output, stats = processor.process(records, context, MixedStrategy())

        assert stats.success == 1
        assert stats.failed == 1

    def test_exhausted_results_counted(self):
        """Exhausted results are tracked in stats."""

        class ExhaustedStrategy:
            def invoke(self, records, context):
                return [
                    ProcessingResult.exhausted(
                        error="retries exceeded",
                        data=[{"content": {"test_action": None}, "_unprocessed": True}],
                        source_guid="sg-1",
                    )
                ]

        processor = UnifiedProcessor()
        records = [_make_record("sg-1")]
        context = _make_context()

        _output, stats = processor.process(records, context, ExhaustedStrategy())

        assert stats.exhausted == 1


# ---------------------------------------------------------------------------
# UnifiedProcessor — edge cases
# ---------------------------------------------------------------------------


class TestUnifiedProcessorEdgeCases:
    """Edge cases and error scenarios."""

    def test_strategy_returning_empty_results(self):
        """Strategy may return fewer results than input records."""

        class DroppingStrategy:
            def invoke(self, records, context):
                return []

        processor = UnifiedProcessor()
        records = [_make_record("sg-1")]
        context = _make_context()

        output, stats = processor.process(records, context, DroppingStrategy())

        assert output == []
        assert stats.success == 0

    def test_strategy_returning_multiple_results_per_record(self):
        """Strategy may produce N:M output (e.g., FILE tool fan-out)."""

        class FanOutStrategy:
            def invoke(self, records, context):
                return [
                    ProcessingResult.success(
                        data=[
                            {"content": {"test_action": {"i": 1}}},
                            {"content": {"test_action": {"i": 2}}},
                        ],
                        source_guid="sg-1",
                    )
                ]

        processor = UnifiedProcessor()
        records = [_make_record("sg-1")]
        context = _make_context()

        output, stats = processor.process(records, context, FanOutStrategy())

        assert stats.success == 1
        assert len(output) == 2

    def test_large_batch(self):
        """Processor handles reasonable batch sizes without error."""
        processor = UnifiedProcessor()
        strategy = NoOpStrategy()
        records = [_make_record(f"sg-{i}") for i in range(100)]
        context = _make_context()

        output, stats = processor.process(records, context, strategy)

        assert stats.success == 100
        assert len(output) == 100


# ---------------------------------------------------------------------------
# ProcessingStrategy protocol compliance
# ---------------------------------------------------------------------------


class TestProcessingStrategyProtocol:
    """Verify protocol structural typing works correctly."""

    def test_class_with_correct_signature_satisfies_protocol(self):
        class ValidStrategy:
            def invoke(
                self, records: list[dict], context: ProcessingContext
            ) -> list[ProcessingResult]:
                return []

        assert isinstance(ValidStrategy(), ProcessingStrategy)

    def test_lambda_does_not_satisfy_protocol(self):
        # A plain function object does not satisfy a Protocol with invoke method
        assert not isinstance(lambda r, c: [], ProcessingStrategy)
