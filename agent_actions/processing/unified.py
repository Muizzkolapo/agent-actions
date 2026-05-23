"""Unified record processing pipeline.

Provides the shared skeleton that all processing paths (online LLM, FILE tool,
HITL, batch result) pass through. Each path supplies a ProcessingStrategy
that controls the actual invocation step; everything else (guard filtering,
enrichment, result collection) is handled uniformly by UnifiedProcessor.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from agent_actions.processing.cascade_filter import partition_cascade_records
from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.record_helpers import build_tombstone
from agent_actions.processing.result_collector import CollectionStats, ResultCollector
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.reasons import GUARD_PREFILTER_SKIP, GUARD_SKIP
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

if TYPE_CHECKING:
    from agent_actions.processing.disposition_gate import DispositionGate

logger = logging.getLogger(__name__)

_LIFECYCLE_KEYS: frozenset[str] = frozenset({"_state", "_state_history", "_state_schema_version"})


@runtime_checkable
class ProcessingStrategy(Protocol):
    """Strategy protocol for the unified processing pipeline.

    Each concrete strategy handles its own domain-specific logic:
    - Prompt rendering and LLM calls (online)
    - Tool invocation with TrackedItem wrapping (FILE tool)
    - HITL state management and decision broadcast (FILE HITL)
    - Batch result reconciliation (batch)

    The strategy receives only records that passed the guard filter and
    cascade filter (upstream-failed records are quarantined by the processor).
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

    Shared skeleton: guard -> cascade filter -> invoke -> enrich -> collect.
    The strategy controls only the invocation step.
    """

    def __init__(
        self,
        *,
        enrichment_pipeline: EnrichmentPipeline | None = None,
        disposition_gate: DispositionGate | None = None,
    ) -> None:
        self._enrichment_pipeline = enrichment_pipeline or EnrichmentPipeline()
        self._disposition_gate = disposition_gate

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
            2. Cascade filter — quarantine upstream-failed records
            3. Invoke strategy — process remaining records
            4. Enrich — add lineage, metadata, version IDs, passthrough fields
            5. Collect — flatten results into output records with dispositions

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

        carry_results: list[ProcessingResult] = []
        if self._disposition_gate is not None and passing:
            to_process, carry_ids = self._disposition_gate.filter(passing, context.action_name)
            if carry_ids:
                relative_path = self._get_carry_forward_path(context)
                if relative_path and context.storage_backend:
                    from agent_actions.processing.disposition_gate import (
                        CARRY_FORWARD_REASON,
                        build_carry_forward,
                    )

                    carry_data, missing_ids = build_carry_forward(
                        carry_ids,
                        context.action_name,
                        relative_path,
                        context.storage_backend,
                    )
                    if missing_ids:
                        to_process.extend(r for r in passing if r.get("source_guid") in missing_ids)
                    for record in carry_data:
                        if raw_records is not None:
                            carry_results.append(
                                ProcessingResult.unprocessed(
                                    data=[record],
                                    reason=CARRY_FORWARD_REASON,
                                    source_guid=record.get("source_guid"),
                                )
                            )
                        else:
                            carry_results.append(
                                ProcessingResult(
                                    status=ProcessingStatus.SUCCESS,
                                    data=[record],
                                    source_guid=record.get("source_guid"),
                                    skip_reason=CARRY_FORWARD_REASON,
                                )
                            )
                else:
                    to_process = passing
            passing = to_process

        # Cascade filter — quarantine upstream-failed records before strategy
        # sees them.  Strategies only receive processable records.
        processable, quarantined_results = partition_cascade_records(
            passing, action_name=context.agent_name
        )

        # FILE mode: filter context.source_data to maintain positional alignment
        # with processable records (used by reconcile_outputs / HITL broadcast).
        if raw_records is not None and quarantined_results:
            quarantined_guids = {
                r.source_guid for r in quarantined_results if r.source_guid is not None
            }
            context.source_data = [
                s
                for s in (context.source_data or [])
                if s.get("source_guid") not in quarantined_guids
            ]

        invocation_results = strategy.invoke(processable, context) if processable else []

        # FILE mode: sequential processing — record N can reference record N-1's output.
        # RECORD mode: independent — merge order doesn't affect semantics.
        # This divergence is intentional. Do not unify without verifying FILE-mode
        # workflows that depend on sequential accumulation (e.g., multi-pass enrichment).
        if raw_records is not None:
            all_results = quarantined_results + invocation_results + guard_results
        else:
            all_results = guard_results + quarantined_results + invocation_results

        enriched = self._enrich(all_results, context)

        # Carry-forward bypasses enrichment (already has correct lineage)
        if carry_results:
            enriched.extend(carry_results)

        return self._collect(enriched, context)

    @staticmethod
    def _get_carry_forward_path(context: ProcessingContext) -> str | None:
        """Derive relative_path for read_target from ProcessingContext.

        Mirrors FileWriter.write_target() path resolution: if output_directory
        is set, compute the relative path from it (preserving subdirectories).
        Falls back to filename-only when output_directory is unavailable.
        """
        file_path = getattr(context, "file_path", None)
        if not file_path:
            return None
        p = Path(file_path)
        output_dir = getattr(context, "output_directory", None)
        if output_dir:
            try:
                return str(p.relative_to(output_dir))
            except ValueError:
                pass
        return p.name

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
        passing, skipped, _original_passing, filtered = prefilter_by_guard(
            records,
            config,
            context.agent_name,
            agent_indices=context.agent_indices,
            is_first_stage=context.is_first_stage,
            version_context=context.version_context,
            workflow_metadata=context.workflow_metadata,
            dependency_configs=context.dependency_configs,
        )

        guard_results: list[ProcessingResult] = []

        for item in skipped:
            source_guid = item.get("source_guid")
            tombstone = build_tombstone(
                context.action_name,
                item,
                GUARD_SKIP,
                source_guid=source_guid,
            )
            guard_results.append(
                ProcessingResult.skipped(
                    passthrough_data=tombstone,
                    reason=GUARD_SKIP,
                    source_guid=source_guid,
                )
            )

        for item in filtered:
            source_guid = item.get("source_guid") if isinstance(item, dict) else None
            guard_results.append(ProcessingResult.filtered(source_guid=source_guid))

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
        passing, skipped, original_passing, filtered = prefilter_by_guard(
            records,
            config,
            context.agent_name,
            original_data=raw_records,
            agent_indices=context.agent_indices,
            is_first_stage=context.is_first_stage,
            version_context=context.version_context,
            workflow_metadata=context.workflow_metadata,
            dependency_configs=context.dependency_configs,
        )

        guard_results: list[ProcessingResult] = []
        action_name = context.action_name

        for item in skipped:
            if action_name and isinstance(item, dict):
                content = item.get("content")
                if isinstance(content, dict) and action_name not in content:
                    skipped_record = RecordEnvelope.build_skipped(action_name, item)
                    for key in item:
                        if key not in skipped_record and key not in _LIFECYCLE_KEYS:
                            skipped_record[key] = item[key]
                    item = skipped_record
            guard_results.append(
                ProcessingResult.unprocessed(
                    data=[item],
                    reason=GUARD_PREFILTER_SKIP,
                    source_guid=item.get("source_guid") if isinstance(item, dict) else None,
                )
            )

        for item in filtered:
            source_guid = item.get("source_guid") if isinstance(item, dict) else None
            guard_results.append(ProcessingResult.filtered(source_guid=source_guid))

        return passing, guard_results, original_passing

    def enrich_and_collect(
        self,
        results: list[ProcessingResult],
        context: ProcessingContext,
    ) -> tuple[list[dict[str, Any]], CollectionStats]:
        """Enrich and collect pre-computed results.

        Used by batch retrieve where guard filtering and strategy invocation
        happened separately (at batch submit and result processing time).
        The results flow through the shared enrichment pipeline and collector.

        Args:
            results: ProcessingResult objects (from BatchResultStrategy.process).
            context: Batch ProcessingContext for enrichment and collection.

        Returns:
            Tuple of (output_records, CollectionStats).
        """
        enriched = self._enrich(results, context)
        return self._collect(enriched, context)

    def _enrich(
        self,
        results: list[ProcessingResult],
        context: ProcessingContext,
    ) -> list[ProcessingResult]:
        """Run enrichment pipeline on each result.

        Uses per-result ``processing_context`` when set (batch results carry
        their own context with correct record_index and original_row).
        Falls back to the shared context with positional record_index for
        results without their own context (online results and batch error
        results alike).

        Per-record enrichment failures are isolated: a failing record produces
        a FAILED ProcessingResult instead of aborting the entire action.
        """
        enriched: list[ProcessingResult] = []
        for i, r in enumerate(results):
            enrich_ctx = (
                r.processing_context
                if r.processing_context is not None
                else replace(context, record_index=i)
            )
            try:
                enriched.append(self._enrichment_pipeline.enrich(r, enrich_ctx))
            except Exception as e:
                logger.warning("Enrichment failed for record %d: %s", i, e)
                enriched.append(
                    ProcessingResult.failed(
                        error=f"Enrichment failed: {e}",
                        source_guid=r.source_guid,
                        source_snapshot=r.input_record,
                    )
                )
        return enriched

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
