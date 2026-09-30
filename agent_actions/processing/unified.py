"""Unified record processing pipeline.

Provides the shared skeleton that all processing paths (online LLM, FILE tool,
HITL, batch result) pass through. Each path supplies a ProcessingStrategy
that controls the actual invocation step; everything else (guard filtering,
enrichment, result collection) is handled uniformly by UnifiedProcessor.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from agent_actions.errors.processing import ProcessingError
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
from agent_actions.utils.id_generation import IDGenerator
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
        repair_inputs: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], CollectionStats]:
        """Guard-filter, quarantine, invoke, enrich and collect, in that order.

        *raw_records* is the pre-scope list FILE mode passes alongside the scoped
        *records*; the guard is evaluated against it, so it decides which records survive
        rather than only what a survivor carries. RECORD mode omits it. *repair_inputs* is
        the action's input for this file from before a repair narrowed it, required while
        one is in flight because *records* is already narrowed by every caller.
        """
        # Refused here rather than at the guard: a repair narrows both lists by one
        # position list, so an already-mispaired caller arrives at the guard the same
        # length and is paired record-to-wrong-original instead of refused.
        if raw_records is not None and len(raw_records) != len(records):
            raise ProcessingError(
                f"Action '{context.action_name}' was given {len(raw_records)} pre-observe "
                f"records for {len(records)} records. The two are read position for "
                f"position and there is no way to pair them once they differ."
            )

        # Stamp first-stage records at the source BEFORE the guard split, so
        # guard-skipped records carry a (deterministic, content-hash) identity too
        # and are not downgraded to failures at enrichment.
        if context.is_first_stage:
            for record in records:
                if isinstance(record, dict) and not record.get("source_guid"):
                    record["source_guid"] = IDGenerator.derive_source_guid(record)

        # Above the guard, not below it: the guard writes passthrough and skipped,
        # both terminal, so a record still in the input when the guard runs is a
        # record a repair has already decided the fate of.
        repair_carry_ids: set[str] = set()
        if self._disposition_gate is not None and self._disposition_gate.repairing:
            from agent_actions.processing.disposition_gate import positions_named_by_repair

            repairing = self._disposition_gate.repairing
            if repair_inputs is None:
                raise ProcessingError(
                    f"Action '{context.action_name}' is repairing records but was given no "
                    "pre-narrowing input. Without it the gate cannot tell a row of this "
                    "action's own making from one minted upstream, and carries every "
                    "stored row — the duplication that rule exists to prevent."
                )
            # One position list for both: the caller matches raw_records to records,
            # so narrowing them apart is what would pull them out of step.
            kept = positions_named_by_repair(records, repairing)
            if kept is not None:
                records = [records[i] for i in kept]
                if raw_records is not None:
                    raw_records = [raw_records[i] for i in kept]
            repair_carry_ids = self._disposition_gate.carried_past_repair(
                context.action_name, self._get_carry_forward_path(context), repair_inputs
            )

        if raw_records is not None:
            # FILE mode: the guard reads these, and they pair to `records` by position
            passing, guard_results, original_passing = self._guard_filter_file_mode(
                records, context, raw_records
            )
            context.source_data = original_passing
            # prefilter_by_guard returns these index-aligned. Keep the pairing so
            # any later filtering or reordering of `passing` can be replayed onto
            # source_data, which FILE-mode strategies index by position.
            source_by_record = {
                id(rec): original for rec, original in zip(passing, original_passing, strict=True)
            }
        else:
            passing, guard_results = self._guard_filter(records, context)
            source_by_record = {}

        # The guard runs above the gate, so a skipped record is in none of the carry
        # sets while still writing a row under its own identity. A filtered one is
        # excluded outright and writes nothing, which is what the data test reads.
        written_by_guard = {
            result.source_guid for result in guard_results if result.data and result.source_guid
        }

        carry_results: list[ProcessingResult] = []
        to_process = passing
        carry_ids: set[str] = set(repair_carry_ids)
        gate_carry_ids: set[str] = set()
        if self._disposition_gate is not None:
            if passing:
                to_process, gate_carry_ids = self._disposition_gate.filter(
                    passing, context.action_name
                )
                carry_ids |= gate_carry_ids
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
                        # Only the gate's ids name inputs; a repair's name stored rows.
                        produced_by=gate_carry_ids,
                        rewriting=written_by_guard
                        | {rid for r in to_process if (rid := r.get("source_guid"))},
                    )
                    # A repair's carried records are not re-queued when their row is
                    # missing: that would process a record the repair did not name. Never
                    # a gate id — a repaired guid keys no carried row, and on a repair run
                    # only a repaired record reaches the guard.
                    missing_ids -= repair_carry_ids
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

        # Rebuilt from `processable`, not by subtracting guid sets: the gate
        # re-queues un-carryable records at the END of the work list.
        if raw_records is not None:
            context.source_data = [source_by_record[id(rec)] for rec in processable]

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
        """Derive relative_path for read_target from ProcessingContext."""
        from agent_actions.processing.record_helpers import derive_relative_path

        return derive_relative_path(
            getattr(context, "file_path", None),
            getattr(context, "output_directory", None),
        )

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
            source_data=context.source_data or None,
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
        """FILE-mode guard filter, as ``(passing, guard_results, original_passing)``.

        Three differences from ``_guard_filter``: *raw_records* goes down as
        ``original_data``, which is what the guard is evaluated against and what the
        skipped and passing records then reference; a skipped record becomes an
        ``unprocessed()`` result carrying a null-namespace marker rather than a tombstone;
        and ``original_passing`` comes back so the caller can set ``context.source_data``
        for the enricher.
        """
        config = cast(dict[str, Any], context.agent_config)
        passing, skipped, original_passing, filtered = prefilter_by_guard(
            records,
            config,
            context.agent_name,
            original_data=raw_records,
            agent_indices=context.agent_indices,
            source_data=context.source_data or None,
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
        Checkpointing is intentionally disabled — batch results arrive
        atomically and do not need mid-collection checkpoints.

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
            context=context,
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
