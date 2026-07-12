"""Tests for UnifiedProcessor skeleton and ProcessingStrategy protocol."""

from dataclasses import replace
from typing import Any
from unittest.mock import patch

from agent_actions.config.types import RunMode
from agent_actions.processing.enrichment import Enricher, EnrichmentPipeline
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

        # Guard will filter all records — 4th value is the filtered records
        with patch(
            "agent_actions.processing.unified.prefilter_by_guard",
            return_value=([], [], [], [_make_record("sg-1")]),
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
            return_value=([], [skipped_record], [], []),
        ):
            output, stats = processor.process([skipped_record], context, strategy)

        assert stats.skipped == 1
        assert stats.success == 0

    def test_first_stage_guard_skip_record_stamped_at_source(self):
        # A first-stage record without source_guid that the guard SKIPS must still
        # carry a content-hash guid — stamped at the source BEFORE the guard split,
        # so it survives enrichment as SKIPPED instead of being downgraded to FAILED.
        processor = UnifiedProcessor()
        strategy = NoOpStrategy()
        context = _make_context(
            guard={"clause": "item.flag == true", "behavior": "skip"}, is_first_stage=True
        )
        record = {"content": {"source": {"field": "value"}}}  # no source_guid

        with patch(
            "agent_actions.processing.unified.prefilter_by_guard",
            return_value=([], [record], [], []),
        ):
            output, stats = processor.process([record], context, strategy)

        assert stats.skipped == 1
        assert stats.success == 0  # not downgraded to a failure by the enrichment raise
        assert output and output[0].get("source_guid")  # born at the source

    def test_filtered_records_excluded_from_output(self):
        processor = UnifiedProcessor()
        strategy = NoOpStrategy()
        context = _make_context(guard={"clause": "item.flag == true", "behavior": "filter"})

        record = _make_record("sg-filter")

        with patch(
            "agent_actions.processing.unified.prefilter_by_guard",
            return_value=([], [], [], [record]),
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
        filtered_rec = _make_record("sg-filter")
        # 3 total records: 1 passes, 1 skipped, 1 filtered
        all_records = [passing, skipped, filtered_rec]

        with patch(
            "agent_actions.processing.unified.prefilter_by_guard",
            return_value=([passing], [skipped], [passing], [filtered_rec]),
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


# ---------------------------------------------------------------------------
# F9: Enrichment failure isolation
# ---------------------------------------------------------------------------


class TestEnrichmentFailureIsolation:
    """F9: An enrichment failure for one record must not kill the action."""

    def test_enrichment_failure_isolates_to_single_record(self):
        """Record 1 of 3 fails enrichment — records 0 and 2 still succeed."""

        class BombOnSecondEnricher(Enricher):
            def __init__(self):
                self.call_count = 0

            def enrich(self, result, context):
                self.call_count += 1
                if self.call_count == 2:
                    raise RuntimeError("enrichment explosion")
                return result

        enricher = BombOnSecondEnricher()
        pipeline = EnrichmentPipeline(enrichers=[enricher])
        processor = UnifiedProcessor(enrichment_pipeline=pipeline)
        strategy = NoOpStrategy()
        records = [_make_record("sg-1"), _make_record("sg-2"), _make_record("sg-3")]
        context = _make_context()

        output, stats = processor.process(records, context, strategy)

        # Record 1 (index 1) failed enrichment — becomes FAILED
        assert stats.success == 2
        assert stats.failed == 1

    def test_enrichment_failure_records_error_message(self):
        """The failed record carries the enrichment error string."""

        class AlwaysFailEnricher(Enricher):
            def enrich(self, result, context):
                raise ValueError("bad lineage data")

        pipeline = EnrichmentPipeline(enrichers=[AlwaysFailEnricher()])
        processor = UnifiedProcessor(enrichment_pipeline=pipeline)

        # Feed a single result directly through _enrich
        result = ProcessingResult.success(data=[{"x": 1}], source_guid="sg-fail")
        context = _make_context()
        enriched = processor._enrich([result], context)

        assert len(enriched) == 1
        assert enriched[0].status == ProcessingStatus.FAILED
        assert "bad lineage data" in enriched[0].error

    def test_enrichment_failure_preserves_source_guid(self):
        """The failed result carries the original record's source_guid."""

        class FailEnricher(Enricher):
            def enrich(self, result, context):
                raise RuntimeError("boom")

        pipeline = EnrichmentPipeline(enrichers=[FailEnricher()])
        processor = UnifiedProcessor(enrichment_pipeline=pipeline)
        result = ProcessingResult.success(data=[{"x": 1}], source_guid="sg-preserve-me")
        context = _make_context()
        enriched = processor._enrich([result], context)

        assert enriched[0].source_guid == "sg-preserve-me"


# ---------------------------------------------------------------------------
# F6: Batch error results go through enrichment
# ---------------------------------------------------------------------------


class TestBatchErrorEnrichment:
    """F6: Batch error results (no processing_context) must be enriched."""

    def test_batch_error_result_is_enriched(self):
        """A batch FAILED result without processing_context gets enriched."""

        class TagEnricher(Enricher):
            def enrich(self, result, context):
                for item in result.data:
                    item["_enriched"] = True
                return result

        pipeline = EnrichmentPipeline(enrichers=[TagEnricher()])
        processor = UnifiedProcessor(enrichment_pipeline=pipeline)

        # Simulate a batch error result: FAILED, no processing_context
        batch_error = ProcessingResult.failed(error="provider timeout", source_guid="sg-batch-err")
        assert batch_error.processing_context is None

        context = replace(_make_context(), mode=RunMode.BATCH)
        enriched = processor._enrich([batch_error], context)

        # Must have been passed through enrichment (not skipped)
        assert len(enriched) == 1
        # The enricher ran — it should not have been skipped
        assert enriched[0].status == ProcessingStatus.FAILED

    def test_batch_and_online_errors_both_enriched(self):
        """Both batch and online error results go through the same path."""
        enrich_calls = []

        class TrackingEnricher(Enricher):
            def enrich(self, result, context):
                enrich_calls.append(result.source_guid)
                return result

        pipeline = EnrichmentPipeline(enrichers=[TrackingEnricher()])
        processor = UnifiedProcessor(enrichment_pipeline=pipeline)

        error_result = ProcessingResult.failed(error="timeout", source_guid="sg-err")

        # Online mode
        ctx_online = replace(_make_context(), mode=RunMode.ONLINE)
        processor._enrich([error_result], ctx_online)

        # Batch mode
        ctx_batch = replace(_make_context(), mode=RunMode.BATCH)
        processor._enrich([error_result], ctx_batch)

        # Both should have been enriched
        assert enrich_calls == ["sg-err", "sg-err"]


# ---------------------------------------------------------------------------
# F9+F6 interaction: batch error + enrichment failure
# ---------------------------------------------------------------------------


class TestBatchErrorEnrichmentFailure:
    """Combined: batch error result where enrichment itself throws."""

    def test_batch_error_enrichment_failure_isolated(self):
        """Batch error result that fails enrichment doesn't kill other records."""

        class FailOnErrorResultEnricher(Enricher):
            def enrich(self, result, context):
                if result.status == ProcessingStatus.FAILED:
                    raise RuntimeError("cannot enrich error result")
                return result

        pipeline = EnrichmentPipeline(enrichers=[FailOnErrorResultEnricher()])
        processor = UnifiedProcessor(enrichment_pipeline=pipeline)

        results = [
            ProcessingResult.success(data=[{"ok": True}], source_guid="sg-ok"),
            ProcessingResult.failed(error="provider error", source_guid="sg-bad"),
        ]

        context = replace(_make_context(), mode=RunMode.BATCH)
        enriched = processor._enrich(results, context)

        assert len(enriched) == 2
        # First record enriched successfully
        assert enriched[0].status == ProcessingStatus.SUCCESS
        # Second record: enrichment failed, still gets a FAILED result
        assert enriched[1].status == ProcessingStatus.FAILED
        assert "cannot enrich error result" in enriched[1].error
