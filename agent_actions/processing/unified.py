"""Unified record processing pipeline.

Provides the shared skeleton that all processing paths (online LLM, FILE tool,
HITL, batch result) pass through. Each path supplies a ProcessingStrategy
that controls the actual invocation step; everything else (guard filtering,
enrichment, result collection) is handled uniformly by UnifiedProcessor.
"""

import logging
from typing import Any, Protocol, cast, runtime_checkable

from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.record_helpers import build_tombstone
from agent_actions.processing.result_collector import CollectionStats, ResultCollector
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

logger = logging.getLogger(__name__)


@runtime_checkable
class ProcessingStrategy(Protocol):
    """Strategy protocol for the unified processing pipeline.

    Each concrete strategy handles its own domain-specific logic:
    - Prompt rendering and LLM calls (online)
    - Tool invocation with TrackedItem wrapping (FILE tool)
    - HITL state management and decision broadcast (FILE HITL)
    - Batch result reconciliation (batch)

    The strategy receives only records that passed the guard filter.
    It returns one ProcessingResult per logical output (may be 1:1 or N:M
    depending on the strategy).
    """

    def invoke(
        self,
        records: list[dict[str, Any]],
        context: ProcessingContext,
    ) -> list[ProcessingResult]:
        """Process records and return results."""
        ...


class UnifiedProcessor:
    """Unified record processing pipeline.

    Shared skeleton: guard -> invoke -> enrich -> collect.
    The strategy controls only the invocation step.
    """

    def __init__(
        self,
        *,
        enrichment_pipeline: EnrichmentPipeline | None = None,
    ) -> None:
        self._enrichment_pipeline = enrichment_pipeline or EnrichmentPipeline()

    def process(
        self,
        records: list[dict[str, Any]],
        context: ProcessingContext,
        strategy: ProcessingStrategy,
    ) -> tuple[list[dict[str, Any]], CollectionStats]:
        """Run records through the full processing pipeline.

        Steps:
            1. Guard filter — split records into passing/skipped/filtered
            2. Invoke strategy — process passing records
            3. Enrich — add lineage, metadata, version IDs, passthrough fields
            4. Collect — flatten results into output records with dispositions

        Returns:
            Tuple of (output_records, stats).
        """
        passing, guard_results = self._guard_filter(records, context)

        invocation_results = strategy.invoke(passing, context) if passing else []

        enriched = self._enrich(guard_results + invocation_results, context)

        return self._collect(enriched, context)

    def _guard_filter(
        self,
        records: list[dict[str, Any]],
        context: ProcessingContext,
    ) -> tuple[list[dict[str, Any]], list[ProcessingResult]]:
        """Apply guard filtering and return (passing_records, guard_results).

        Records that fail the guard become ProcessingResult objects immediately
        (SKIPPED or FILTERED). Records that pass are forwarded to the strategy.
        """
        config = cast(dict[str, Any], context.agent_config)
        passing, skipped, _original_passing = prefilter_by_guard(
            records,
            config,
            context.agent_name,
        )

        guard_results: list[ProcessingResult] = []

        for item in skipped:
            source_guid = item.get("source_guid")
            tombstone = build_tombstone(
                context.action_name,
                item,
                "guard_skip",
                source_guid=source_guid,
            )
            guard_results.append(
                ProcessingResult.skipped(
                    passthrough_data=tombstone,
                    reason="guard_skip",
                    source_guid=source_guid,
                )
            )

        filtered_count = len(records) - len(passing) - len(skipped)
        for _i in range(filtered_count):
            guard_results.append(ProcessingResult.filtered(source_guid=None))

        return passing, guard_results

    def _enrich(
        self,
        results: list[ProcessingResult],
        context: ProcessingContext,
    ) -> list[ProcessingResult]:
        """Run enrichment pipeline on each result."""
        return [self._enrichment_pipeline.enrich(r, context) for r in results]

    def _collect(
        self,
        results: list[ProcessingResult],
        context: ProcessingContext,
    ) -> tuple[list[dict[str, Any]], CollectionStats]:
        """Collect results into output records with stats."""
        return ResultCollector.collect_results(
            results,
            cast(dict[str, Any], context.agent_config),
            context.agent_name,
            is_first_stage=context.is_first_stage,
            storage_backend=context.storage_backend,
        )


class NoOpStrategy:
    """Pass-through strategy for testing the skeleton in isolation.

    Returns each input record as a successful ProcessingResult with
    no transformation applied.
    """

    def invoke(
        self,
        records: list[dict[str, Any]],
        context: ProcessingContext,
    ) -> list[ProcessingResult]:
        """Return each record as-is wrapped in a success result."""
        return [
            ProcessingResult.success(data=[record], source_guid=record.get("source_guid"))
            for record in records
        ]
