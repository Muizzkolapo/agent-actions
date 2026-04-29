"""Unified record processing pipeline.

Provides the shared skeleton that all processing paths (online LLM, FILE tool,
HITL, batch result) pass through. Each path supplies a ProcessingStrategy
that controls the actual invocation step; everything else (guard filtering,
enrichment, result collection) is handled uniformly by UnifiedProcessor.
"""

import logging
from typing import Any, Protocol, cast, runtime_checkable

from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.record_helpers import build_guard_skipped_record
from agent_actions.processing.result_collector import CollectionStats, ResultCollector
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.record.envelope import RecordEnvelope
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
        *,
        raw_records: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], CollectionStats]:
        """Run records through the full processing pipeline.

        Steps:
            1. Guard filter — split records into passing/skipped/filtered
            2. Invoke strategy — process passing records
            3. Enrich — add lineage, metadata, version IDs, passthrough fields
            4. Collect — flatten results into output records with dispositions

        Args:
            records: Input records.  For FILE mode these are context-scope-
                filtered; for RECORD mode they are the raw input.
            context: Shared processing context.
            strategy: Strategy that handles the invocation step.
            raw_records: Pre-context-scope records (FILE mode only).  When
                provided, the guard filter uses these as ``original_data``
                so that skipped/passing records reference pre-observe fields.
                RECORD mode callers should omit this parameter.

        Returns:
            Tuple of (output_records, stats).
        """
        if raw_records is not None:
            # FILE mode: guard needs original_data for pre-observe alignment
            passing, guard_results, original_passing = self._guard_filter_file_mode(
                records, context, raw_records
            )
            context.source_data = original_passing
        else:
            passing, guard_results = self._guard_filter(records, context)

        invocation_results = strategy.invoke(passing, context) if passing else []

        # FILE mode: invocation first, then guard skips (preserves historical order).
        # RECORD mode: guard skips first, then invocation results.
        if raw_records is not None:
            all_results = invocation_results + guard_results
        else:
            all_results = guard_results + invocation_results

        enriched = self._enrich(all_results, context)

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
            tombstone = build_guard_skipped_record(
                context.action_name,
                item,
                source_guid=source_guid,
                clause=str(config.get("guard", {}).get("clause", ""))
                if isinstance(config, dict)
                else "",
                behavior="skip",
                result=False,
            )
            guard_results.append(
                ProcessingResult.skipped(
                    passthrough_data=tombstone,
                    reason="guard_skipped",
                    source_guid=source_guid,
                )
            )

        filtered_count = len(records) - len(passing) - len(skipped)
        for _i in range(filtered_count):
            guard_results.append(ProcessingResult.filtered(source_guid=None))

        return passing, guard_results

    def _guard_filter_file_mode(
        self,
        records: list[dict[str, Any]],
        context: ProcessingContext,
        raw_records: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[ProcessingResult], list[dict[str, Any]]]:
        """FILE-mode guard filter with original_data alignment.

        Differs from ``_guard_filter`` in three ways:

        1. Passes ``original_data`` to ``prefilter_by_guard`` so that
           skipped/passing records reference pre-context-scope fields.
        2. Skipped records produce ``ProcessingResult.unprocessed()`` with
           ``RecordEnvelope.build_skipped()`` (adds a null namespace marker)
           rather than ``ProcessingResult.skipped()`` with a tombstone.
        3. Returns ``original_passing`` so the caller can set
           ``context.source_data`` for the enricher.

        Returns:
            (passing, guard_results, original_passing)
        """
        config = cast(dict[str, Any], context.agent_config)
        passing, skipped, original_passing = prefilter_by_guard(
            records,
            config,
            context.agent_name,
            original_data=raw_records,
        )

        guard_results: list[ProcessingResult] = []
        action_name = context.action_name

        for item in skipped:
            if action_name and isinstance(item, dict):
                content = item.get("content")
                if isinstance(content, dict) and action_name not in content:
                    skipped_record = RecordEnvelope.build_skipped(action_name, item)
                    for key in item:
                        if key not in skipped_record:
                            skipped_record[key] = item[key]
                    item = skipped_record
            guard_results.append(
                ProcessingResult.unprocessed(
                    data=[item],
                    reason="guard_prefilter_skip",
                    source_guid=item.get("source_guid") if isinstance(item, dict) else None,
                )
            )

        filtered_count = len(records) - len(passing) - len(skipped)
        for _i in range(filtered_count):
            guard_results.append(ProcessingResult.filtered(source_guid=None))

        return passing, guard_results, original_passing

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
