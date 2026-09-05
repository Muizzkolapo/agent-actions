"""Shared result aggregation for processing output records."""

import collections
import json
import logging
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any, Optional

from agent_actions.errors import AgentActionsError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    ExhaustedRecordEvent,
    ResultCollectedEvent,
    ResultCollectionCompleteEvent,
    ResultCollectionStartedEvent,
)
from agent_actions.processing.disposition_gate import CARRY_FORWARD_REASON
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.reasons import (
    COLLAPSED_INTO_OUTPUT,
    GUARD_FILTER,
    GUARD_PREFILTER_SKIP,
    GUARD_SKIP,
    PARSE_ERROR,
    RETRY_EXHAUSTED,
    SUCCESS,
    UNPROCESSED,
)
from agent_actions.record.state import RecordState
from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SKIPPED,
    DISPOSITION_SUCCESS,
    DISPOSITION_UNPROCESSED,
    NODE_LEVEL_RECORD_ID,
    DispositionRow,
)

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


def _stamp(record: dict[str, Any], state: RecordState, action_name: str, reason: str) -> None:
    """Stamp lifecycle state on a record entering output.

    Records arrive ACTIVE (after downstream reset) or CASCADE_BLOCKING.
    ACTIVE → any settled is legal. CASCADE_BLOCKING → CASCADE_SKIPPED
    is legal (cascade propagation). Same → same is a no-op.
    """
    RecordEnvelope.transition(record, state, action_name, reason)


def _spent_its_retries(result: ProcessingResult) -> bool:
    """Whether the retry loop gave up on *result*.

    A record the provider answered with a per-record error keeps its FAILED
    status so that error survives into the output, so status alone would miss
    exactly the case the policy exists for. Both run modes set ``succeeded``
    False only once the attempts are spent.
    """
    if result.status == ProcessingStatus.EXHAUSTED:
        return True
    retry = result.recovery_metadata.retry if result.recovery_metadata else None
    return result.status == ProcessingStatus.FAILED and retry is not None and not retry.succeeded


def _get_retry_attempts(result: ProcessingResult) -> str | int:
    """Extract retry attempt count from a result's recovery metadata.

    Returns the integer attempt count if available, otherwise ``"unknown"``.
    """
    if result.recovery_metadata and result.recovery_metadata.retry:
        return result.recovery_metadata.retry.attempts
    if result.recovery_metadata and result.recovery_metadata.expectations:
        return result.recovery_metadata.expectations.attempts
    return "unknown"


@dataclass
class CollectionStats:
    """Counts from result collection — returned alongside output records."""

    success: int = 0
    failed: int = 0
    skipped: int = 0
    filtered: int = 0
    exhausted: int = 0
    deferred: int = 0
    unprocessed: int = 0
    carry_forward: int = 0

    @property
    def only_guard_outcomes(self) -> bool:
        """True when every collected record was guard-skipped or guard-filtered.

        Uses ``dataclasses.fields()`` so that adding a new status field
        automatically makes this return False until the new field is
        accounted for — no manual update needed.
        """
        total: int = sum(getattr(self, f.name) for f in fields(self))
        return bool((self.skipped + self.filtered) == total)

    def raise_if_terminal_failure(
        self,
        action_name: str,
        data: list,
        output: list,
        storage_backend: Optional["StorageBackend"] = None,
    ) -> None:
        """Raise RuntimeError if all active records failed.

        Handles two cases:

        1. **only_guard_outcomes** with no output — write a node-level
           SKIPPED disposition so the executor can cascade-skip downstream.
           Guard-skipped records with passthrough data ARE in ``output``,
           so ``not output`` prevents cascade-blocking when passthrough
           data exists.
        2. **zero successes** among active (non-unprocessed) input records
           with at least one failure — raise ``RuntimeError`` for the
           circuit breaker.  Unprocessed (cascade-quarantined) records are
           excluded from the denominator so pass-through-only actions
           don't erroneously trip the breaker.
        """
        if data and self.only_guard_outcomes and not output:
            write_node_level_disposition(
                storage_backend,
                action_name,
                DISPOSITION_SKIPPED,
                "All records filtered — no output produced",
            )
            return

        active_input_count = len(data) - self.unprocessed
        if active_input_count > 0 and self.success == 0 and (self.failed + self.exhausted) > 0:
            raise RuntimeError(
                f"Action '{action_name}' produced 0 successful records — "
                f"all {active_input_count} active input item(s) failed or exhausted "
                f"({self.failed} failed, {self.exhausted} exhausted)"
            )


def _build_failed_tombstone(
    agent_name: str,
    source_guid: str | None,
    input_record: dict[str, Any] | None,
    error: str | None,
) -> dict[str, Any]:
    """Build a tombstone record for a FAILED processing result.

    The tombstone preserves lineage fields (source_guid, root_target_id,
    content from upstream) so downstream actions see the record and can
    cascade-skip it.  This closes the "vanishing record" gap where FAILED
    records previously disappeared from the output stream.
    """
    from agent_actions.processing.record_helpers import build_tombstone

    tombstone = build_tombstone(
        agent_name,
        input_record,
        error or "processing_error",
        source_guid=source_guid,
    )
    _stamp(tombstone, RecordState.FAILED, agent_name, error or "processing_error")
    return tombstone


def _data_has_parse_error(data: list[dict[str, Any]]) -> bool:
    """Check if any data item contains a ``_parse_error`` from the LLM provider.

    The error dict produced by ``JSONResponseMixin`` flows through the transform
    pipeline and lands inside ``content.{action_namespace}._parse_error``.
    """
    for item in data:
        content = item.get("content")
        if isinstance(content, dict):
            for ns_value in content.values():
                if isinstance(ns_value, dict) and "_parse_error" in ns_value:
                    return True
        # Check top-level (raw shape before transform)
        if "_parse_error" in item:
            return True
    return False


def _serialize_snapshot(source: dict[str, Any] | None) -> str | None:
    """Serialize a source snapshot dict to JSON for disposition storage.

    Returns None if source is missing, not a dict, or not serializable.
    Truncation to 10KB is handled downstream by sqlite_backend.set_disposition().
    """
    # Empty dict ({}) is treated as absent — reconciler returns {} for missing
    # records, and an empty snapshot has no debugging value.
    if not source or not isinstance(source, dict):
        return None
    try:
        return json.dumps(source, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        logger.debug("Could not serialize input snapshot: %s", type(source).__name__, exc_info=True)
        return None


def _per_item_dispositions(
    pending: list[DispositionRow],
    action_name: str,
    data: list[dict[str, Any]],
    disposition: str,
    reason: str | None = None,
    input_snapshot: str | None = None,
    detail: str | None = None,
) -> int:
    """Write per-item dispositions when the result-level source_guid is None.

    FILE-mode results bundle multiple records into one ProcessingResult with
    source_guid=None.  Individual data items carry their own source_guid.

    Returns the count of items that had a usable source_guid.
    """
    written = 0
    for item in data:
        item_guid = item.get("source_guid")
        if item_guid:
            pending.append(
                (action_name, item_guid, disposition, reason, None, input_snapshot, detail)
            )
            written += 1
    if not written and data:
        logger.warning(
            "[%s] %d data item(s) but none carry source_guid — "
            "dispositions not written (risk of reprocessing on next run)",
            action_name,
            len(data),
        )
    return written


def _safe_set_disposition(
    backend: "StorageBackend",
    action_name: str,
    record_id: str,
    disposition: str,
    **kwargs: Any,
) -> None:
    """Write a disposition record — log ERROR on failure, do not crash pipeline."""
    try:
        backend.set_disposition(action_name, record_id, disposition, **kwargs)
    except Exception:
        logger.exception(
            "Failed to write disposition action=%s record=%s disp=%s — "
            "disposition may diverge from _state until next run",
            action_name,
            record_id,
            disposition,
        )


def write_node_level_disposition(
    storage_backend: Optional["StorageBackend"],
    action_name: str,
    disposition: str,
    reason: str,
) -> None:
    """Write a node-level disposition for an entire action.

    Used when all records in an action were skipped or passthroughed,
    so there is no per-record output to disposition.
    """
    if storage_backend is None:
        return
    _safe_set_disposition(
        storage_backend, action_name, NODE_LEVEL_RECORD_ID, disposition, reason=reason
    )


def write_record_dispositions(
    storage_backend: Optional["StorageBackend"],
    items: list[dict[str, Any]],
    action_name: str,
) -> None:
    """Write dispositions for batch output records.

    Called after batch results have been converted to workflow format.
    Writes the terminal disposition first (SUCCESS, EXHAUSTED, FAILED,
    PASSTHROUGH, UNPROCESSED), then clears the prior DEFERRED
    disposition.  This ordering is crash-safe: if the process dies
    between the two operations the terminal state is already committed
    and queryable.  The UNIQUE constraint on (action_name, record_id,
    disposition) allows both rows to coexist since the disposition
    values differ.

    Disposition writes are telemetry — errors are logged but never propagated.
    """
    if not storage_backend:
        return
    for item in items:
        source_guid = item.get("source_guid")
        if not source_guid:
            logger.warning(
                "[%s] Batch output item missing source_guid — "
                "disposition not written (risk of reprocessing on next run). "
                "Item keys: %s",
                action_name,
                sorted(item.keys())[:10],
            )
            continue
        metadata = item.get("metadata", {})

        recovery = item.get("_recovery", {})
        reprompt_recovery = recovery.get("reprompt", {})
        if reprompt_recovery.get("passed") is False:
            validation = reprompt_recovery.get("validation", "unknown")
            _safe_set_disposition(
                storage_backend,
                action_name,
                source_guid,
                DISPOSITION_EXHAUSTED,
                reason=f"evaluation_exhausted:{validation}",
                input_snapshot=_serialize_snapshot(item),
            )
        elif metadata.get("retry_exhausted"):
            # The marker flag is set on every exhausted tombstone; the actual
            # cause lives in the tombstone's own reason field.
            _safe_set_disposition(
                storage_backend,
                action_name,
                source_guid,
                DISPOSITION_EXHAUSTED,
                reason=metadata.get("reason", RETRY_EXHAUSTED),
                input_snapshot=_serialize_snapshot(item),
            )
        elif item.get("_state") in (
            RecordState.CASCADE_SKIPPED.value,
            RecordState.GUARD_SKIPPED.value,
        ):
            from agent_actions.record.disposition import derive_disposition

            _safe_set_disposition(
                storage_backend,
                action_name,
                source_guid,
                derive_disposition(item),
                reason=metadata.get("reason", UNPROCESSED),
            )
        elif item.get("error"):
            error_str = str(item["error"])[:500]
            _safe_set_disposition(
                storage_backend,
                action_name,
                source_guid,
                DISPOSITION_FAILED,
                reason=error_str,
                input_snapshot=_serialize_snapshot(item),
                detail=error_str,
            )
        elif item.get("_state") == RecordState.PROCESSED.value:
            _safe_set_disposition(
                storage_backend,
                action_name,
                source_guid,
                DISPOSITION_SUCCESS,
            )

        try:
            storage_backend.clear_disposition(
                action_name,
                disposition=DISPOSITION_DEFERRED,
                record_id=source_guid,
            )
        except Exception:
            logger.debug(
                "Could not clear DEFERRED disposition for %s (may not exist)",
                source_guid,
                exc_info=True,
            )


def collect_results_from_processing_results(
    results: list[ProcessingResult],
    action_name: str,
    *,
    storage_backend: Optional["StorageBackend"] = None,
    agent_config: dict[str, Any] | None = None,
    context: ProcessingContext | None = None,
) -> tuple[list[dict[str, Any]], CollectionStats]:
    """Shared collect logic for both online and batch retrieve paths.

    Flattens ProcessingResult entries into output records, stamps lifecycle
    state on each, writes dispositions to storage, and fires telemetry events.

    Args:
        results: ProcessingResult objects to collect (enriched).
        action_name: Name of the action being processed.
        storage_backend: Optional storage for disposition writes.
        agent_config: Agent configuration (used for exhausted-raise check
            and guard metadata in completion events). Pass ``None`` when
            calling from batch retrieve — exhausted-raise is not applicable
            and guard metadata is absent.

    Returns:
        Tuple of (output_records, stats). Stats contain counts by status.

    Raises:
        AgentActionsError: If on_exhausted=raise and records exhausted retries,
            unless *context* asks for it to be deferred — batch writes its output
            once at the end, so it parks the error and raises after the write.
    """
    effective_config: dict[str, Any] = agent_config if agent_config is not None else {}

    fire_event(
        ResultCollectionStartedEvent(
            action_name=action_name,
            total_results=len(results),
        )
    )

    if agent_config is not None:
        exhaustion = ResultCollector._handle_exhausted_policy(
            results, effective_config, action_name, storage_backend
        )
        if exhaustion is not None:
            if context is not None and context.defer_exhaustion:
                context.pending_exhaustion = exhaustion
            else:
                raise exhaustion

    output: list[dict[str, Any]] = []
    stats: collections.Counter[str] = collections.Counter()
    pending_dispositions: list[DispositionRow] = []

    for idx, result in enumerate(results):
        status = result.status
        status_key = status.value
        stats[status_key] += 1

        if status == ProcessingStatus.SUCCESS:
            data = result.data or []

            if result.skip_reason == CARRY_FORWARD_REASON:
                if data:
                    output.extend(data)
                stats[status_key] -= 1
                stats["carry_forward"] += 1
                continue

            # Detect parse-error records masquerading as SUCCESS.
            # The LLM provider returns {"_parse_error": ...} on JSON
            # parse failure, which flows through as SUCCESS data.
            # Reprompt has already had its chance to repair (it runs
            # during invocation, before result collection).
            if data and _data_has_parse_error(data):
                result.status = ProcessingStatus.FAILED
                for d in data:
                    _stamp(d, RecordState.FAILED, action_name, PARSE_ERROR)
                output.extend(data)
                stats[status_key] -= 1
                stats["failed"] += 1
                logger.warning(
                    "[%s] SUCCESS result source_guid=%s contains _parse_error "
                    "— dispositioned as FAILED",
                    action_name,
                    result.source_guid,
                )
                fire_event(
                    ResultCollectedEvent(
                        action_name=action_name,
                        result_index=idx,
                        status="failed",
                    )
                )
                if storage_backend and result.source_guid:
                    pending_dispositions.append(
                        (
                            action_name,
                            result.source_guid,
                            DISPOSITION_FAILED,
                            PARSE_ERROR,
                            None,
                            None,
                            None,
                        )
                    )
                elif storage_backend and result.source_guid is None and data:
                    _per_item_dispositions(
                        pending_dispositions,
                        action_name,
                        data,
                        DISPOSITION_FAILED,
                        reason=PARSE_ERROR,
                    )
                continue

            if data:
                for d in data:
                    _stamp(d, RecordState.PROCESSED, action_name, SUCCESS)
                output.extend(data)
            logger.debug(
                "Collected SUCCESS result source_guid=%s count=%d",
                result.source_guid,
                len(data),
            )
            fire_event(
                ResultCollectedEvent(
                    action_name=action_name,
                    result_index=idx,
                    status="success",
                )
            )
            if storage_backend and result.source_guid:
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_SUCCESS,
                        None,
                        None,
                        None,
                        None,
                    )
                )
            elif storage_backend and result.source_guid is None and data:
                _per_item_dispositions(
                    pending_dispositions,
                    action_name,
                    data,
                    DISPOSITION_SUCCESS,
                )
            if storage_backend:
                for guid in result.collapse_contributor_guids:
                    pending_dispositions.append(
                        (
                            action_name,
                            guid,
                            DISPOSITION_SUCCESS,
                            COLLAPSED_INTO_OUTPUT,
                            None,
                            None,
                            None,
                        )
                    )

        elif status == ProcessingStatus.SKIPPED:
            data = result.data or []
            if data:
                for d in data:
                    _stamp(
                        d,
                        RecordState.GUARD_SKIPPED,
                        action_name,
                        result.skip_reason or GUARD_SKIP,
                    )
                output.extend(data)
            logger.debug(
                "Collected SKIPPED result source_guid=%s count=%d",
                result.source_guid,
                len(data),
            )
            fire_event(
                ResultCollectedEvent(
                    action_name=action_name,
                    result_index=idx,
                    status="skipped",
                )
            )
            if storage_backend and result.source_guid:
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_PASSTHROUGH,
                        result.skip_reason or GUARD_SKIP,
                        None,
                        None,
                        None,
                    )
                )
            elif storage_backend and result.source_guid is None and data:
                _per_item_dispositions(
                    pending_dispositions,
                    action_name,
                    data,
                    DISPOSITION_PASSTHROUGH,
                    reason=result.skip_reason or GUARD_SKIP,
                )

        elif status == ProcessingStatus.EXHAUSTED:
            data = result.data or []
            if data:
                for d in data:
                    _stamp(
                        d,
                        RecordState.EXHAUSTED,
                        action_name,
                        d.get("_tombstone_reason") or RETRY_EXHAUSTED,
                    )
                output.extend(data)
            attempts = _get_retry_attempts(result)
            logger.debug(
                "Collected EXHAUSTED result source_guid=%s attempts=%s",
                result.source_guid,
                attempts,
            )
            fire_event(
                ExhaustedRecordEvent(
                    action_name=action_name,
                    record_index=idx,
                    source_guid=result.source_guid or "",
                    reason=f"exhausted_after_{attempts}_attempts",
                )
            )
            if storage_backend and result.source_guid:
                input_snapshot_str = _serialize_snapshot(
                    result.source_snapshot or result.input_record
                )
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_EXHAUSTED,
                        f"exhausted_after_{attempts}_attempts",
                        None,
                        input_snapshot_str,
                        result.error,
                    )
                )
            elif storage_backend and result.source_guid is None and data:
                input_snapshot_str = _serialize_snapshot(
                    result.source_snapshot or result.input_record
                )
                _per_item_dispositions(
                    pending_dispositions,
                    action_name,
                    data,
                    DISPOSITION_EXHAUSTED,
                    reason=f"exhausted_after_{attempts}_attempts",
                    input_snapshot=input_snapshot_str,
                    detail=result.error,
                )

        elif status == ProcessingStatus.FAILED:
            logger.error(
                "[%s] Processing failed for source_guid=%s: %s",
                action_name,
                result.source_guid,
                result.error,
            )

            if result.data:
                # Batch FAILED results carry their own data (error items or
                # tombstones from build_tombstone).  Preserve them as-is and
                # stamp lifecycle state.
                for d in result.data:
                    _stamp(d, RecordState.FAILED, action_name, result.error or "processing_error")
                output.extend(result.data)
            else:
                # Online FAILED results have data=[].  Build a tombstone so
                # downstream actions see this record and can cascade-skip it
                # (record-level error isolation).
                tombstone = _build_failed_tombstone(
                    action_name, result.source_guid, result.input_record, result.error
                )
                output.append(tombstone)

            fire_event(
                ResultCollectedEvent(
                    action_name=action_name,
                    result_index=idx,
                    status="failed",
                )
            )
            if storage_backend and result.source_guid:
                input_snapshot_str = _serialize_snapshot(
                    result.source_snapshot or result.input_record
                )
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_FAILED,
                        result.error or "processing_error",
                        None,
                        input_snapshot_str,
                        result.error,
                    )
                )
            elif storage_backend and result.source_guid is None:
                failed_items = result.data or []
                if failed_items:
                    input_snapshot_str = _serialize_snapshot(
                        result.source_snapshot or result.input_record
                    )
                    _per_item_dispositions(
                        pending_dispositions,
                        action_name,
                        failed_items,
                        DISPOSITION_FAILED,
                        reason=result.error or "processing_error",
                        input_snapshot=input_snapshot_str,
                        detail=result.error,
                    )
                else:
                    logger.warning(
                        "[%s] FAILED result has no source_guid and no data — "
                        "disposition not written (risk of reprocessing on next run)",
                        action_name,
                    )

        elif status == ProcessingStatus.FILTERED:
            logger.debug("Collected FILTERED result source_guid=%s", result.source_guid)
            fire_event(
                ResultCollectedEvent(
                    action_name=action_name,
                    result_index=idx,
                    status="filtered",
                )
            )
            if storage_backend and result.source_guid:
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_FILTERED,
                        result.skip_reason or GUARD_FILTER,
                        None,
                        None,
                        None,
                    )
                )
            elif storage_backend and result.source_guid is None:
                filtered_data = result.data or []
                if filtered_data:
                    _per_item_dispositions(
                        pending_dispositions,
                        action_name,
                        filtered_data,
                        DISPOSITION_FILTERED,
                        reason=result.skip_reason or GUARD_FILTER,
                    )
                else:
                    logger.warning(
                        "[%s] FILTERED result has no source_guid and no data — "
                        "disposition not written (risk of reprocessing on next run)",
                        action_name,
                    )

        elif status == ProcessingStatus.UNPROCESSED:
            data = result.data or []

            if result.skip_reason == CARRY_FORWARD_REASON:
                if data:
                    output.extend(data)
                stats[status_key] -= 1
                stats["carry_forward"] += 1
                continue

            if data:
                reason = result.skip_reason or UNPROCESSED
                # FILE prefilter uses UNPROCESSED for ordering (FM13) but is a guard decision
                state = (
                    RecordState.GUARD_SKIPPED
                    if reason in (GUARD_PREFILTER_SKIP, GUARD_SKIP, GUARD_FILTER)
                    else RecordState.CASCADE_SKIPPED
                )
                for d in data:
                    _stamp(d, state, action_name, reason)
                output.extend(data)  # Preserve in output for lineage
            logger.debug(
                "Collected UNPROCESSED result source_guid=%s count=%d",
                result.source_guid,
                len(data),
            )
            fire_event(
                ResultCollectedEvent(
                    action_name=action_name,
                    result_index=idx,
                    status="unprocessed",
                )
            )
            if storage_backend and result.source_guid:
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_UNPROCESSED,
                        result.skip_reason or UNPROCESSED,
                        None,
                        None,
                        None,
                    )
                )
            elif storage_backend and result.source_guid is None and data:
                _per_item_dispositions(
                    pending_dispositions,
                    action_name,
                    data,
                    DISPOSITION_UNPROCESSED,
                    reason=result.skip_reason or UNPROCESSED,
                )

        elif status == ProcessingStatus.DEFERRED:
            task_id = result.task_id or ""
            logger.info(
                "Collected DEFERRED result source_guid=%s task_id=%s",
                result.source_guid,
                task_id,
            )
            fire_event(
                ResultCollectedEvent(
                    action_name=action_name,
                    result_index=idx,
                    status="deferred",
                )
            )
            if storage_backend and result.source_guid:
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_DEFERRED,
                        f"batch_queued:task_id={task_id}",
                        None,
                        None,
                        None,
                    )
                )
            elif storage_backend and result.source_guid is None:
                logger.warning(
                    "[%s] DEFERRED result has no source_guid — "
                    "disposition not written (risk of reprocessing on next run)",
                    action_name,
                )

        else:
            logger.debug("Unhandled result status=%s", status)  # type: ignore[unreachable]

    # Flush all accumulated dispositions in a single transaction.
    if storage_backend and pending_dispositions:
        try:
            storage_backend.set_dispositions_batch(pending_dispositions)
        except Exception:
            logger.exception(
                "Failed to batch-write %d dispositions for %s",
                len(pending_dispositions),
                action_name,
            )

    guard_config = effective_config.get("guard", {})
    guard_condition = guard_config.get("clause", "") if isinstance(guard_config, dict) else ""
    guard_on_false = guard_config.get("behavior", "") if isinstance(guard_config, dict) else ""

    fire_event(
        ResultCollectionCompleteEvent(
            action_name=action_name,
            total_success=stats["success"],
            total_skipped=stats["skipped"],
            total_filtered=stats["filtered"],
            total_failed=stats["failed"],
            total_exhausted=stats["exhausted"],
            total_unprocessed=stats["unprocessed"],
            total_deferred=stats["deferred"],
            guard_condition=guard_condition,
            guard_on_false=guard_on_false,
        )
    )

    total_input = len(results)
    if stats["filtered"] > 0 and stats["filtered"] == total_input and total_input > 0:
        logger.warning(
            "[%s] All %d records filtered by guard (%s). Downstream actions will receive no input.",
            action_name,
            total_input,
            guard_condition or "unknown condition",
        )

    tombstone_count = stats["skipped"] + stats["exhausted"] + stats["unprocessed"]
    if tombstone_count > 0:
        logger.info(
            "[%s] %d/%d records are tombstones (skipped=%d, exhausted=%d, unprocessed=%d)",
            action_name,
            tombstone_count,
            len(results),
            stats["skipped"],
            stats["exhausted"],
            stats["unprocessed"],
        )

    return output, CollectionStats(
        success=stats["success"],
        failed=stats["failed"],
        skipped=stats["skipped"],
        filtered=stats["filtered"],
        exhausted=stats["exhausted"],
        deferred=stats["deferred"],
        unprocessed=stats["unprocessed"],
        carry_forward=stats["carry_forward"],
    )


class ResultCollector:
    """Collect output records from processing results."""

    @staticmethod
    def collect_results(
        results: list[ProcessingResult],
        agent_config: dict[str, Any],
        agent_name: str,
        *,
        is_first_stage: bool,
        storage_backend: Optional["StorageBackend"] = None,
        context: ProcessingContext | None = None,
    ) -> tuple[list[dict[str, Any]], CollectionStats]:
        """Flatten ProcessingResult entries into output records.

        Delegates to ``collect_results_from_processing_results()`` — the
        shared helper used by both online and batch retrieve paths.

        Returns:
            Tuple of (output_records, stats). Stats contain counts by status.

        Raises:
            AgentActionsError: If on_exhausted=raise and records exhausted retries.
        """
        return collect_results_from_processing_results(
            results,
            agent_name,
            storage_backend=storage_backend,
            agent_config=agent_config,
            context=context,
        )

    @staticmethod
    def _handle_exhausted_policy(
        results: list[ProcessingResult],
        agent_config: dict[str, Any],
        agent_name: str,
        storage_backend: Optional["StorageBackend"],
    ) -> Exception | None:
        """Handle exhausted retries according to on_exhausted policy.

        For return_last (default): logs at INFO. For raise: writes EXHAUSTED
        dispositions and hands back the error, leaving the caller to decide when
        to throw it — batch has not written its output file yet.
        """
        exhausted_results = [
            r
            for r in results
            if _spent_its_retries(r)
            # Expectations exhaustion resolved its own on_exhausted policy in
            # the service; the retry config's policy does not apply to it.
            and not (r.recovery_metadata and r.recovery_metadata.expectations)
        ]
        if not exhausted_results:
            return None

        retry_config = agent_config.get("retry") or {}
        on_exhausted = retry_config.get("on_exhausted") or "return_last"

        if on_exhausted != "raise":
            logger.info(
                "[%s] %d records exhausted retries (on_exhausted=%s)",
                agent_name,
                len(exhausted_results),
                on_exhausted,
            )
            return None

        logger.warning(
            "[%s] %d records exhausted retries — raising (on_exhausted=raise)",
            agent_name,
            len(exhausted_results),
        )

        if storage_backend:
            for er in exhausted_results:
                if er.source_guid:
                    input_snapshot_str = _serialize_snapshot(er.source_snapshot or er.input_record)
                    _safe_set_disposition(
                        storage_backend,
                        agent_name,
                        er.source_guid,
                        DISPOSITION_EXHAUSTED,
                        reason=f"exhausted_after_{_get_retry_attempts(er)}_attempts",
                        input_snapshot=input_snapshot_str,
                        detail=er.error,
                    )
                else:
                    er_data = er.data or []
                    if er_data:
                        input_snapshot_str = _serialize_snapshot(
                            er.source_snapshot or er.input_record
                        )
                        written = 0
                        for item in er_data:
                            item_guid = item.get("source_guid")
                            if item_guid:
                                _safe_set_disposition(
                                    storage_backend,
                                    agent_name,
                                    item_guid,
                                    DISPOSITION_EXHAUSTED,
                                    reason=f"exhausted_after_{_get_retry_attempts(er)}_attempts",
                                    input_snapshot=input_snapshot_str,
                                    detail=er.error,
                                )
                                written += 1
                        if not written:
                            logger.warning(
                                "[%s] %d exhausted data item(s) but none carry "
                                "source_guid — dispositions not written "
                                "(on_exhausted=raise)",
                                agent_name,
                                len(er_data),
                            )
                    else:
                        logger.warning(
                            "[%s] Exhausted result has no source_guid and no data — "
                            "disposition not written (on_exhausted=raise)",
                            agent_name,
                        )

        first = exhausted_results[0]
        return AgentActionsError(
            f"Retry exhausted for record {first.source_guid} after "
            f"{_get_retry_attempts(first)} attempts (on_exhausted=raise)",
            context={
                "agent_name": agent_name,
                "exhausted_records": len(exhausted_results),
                "on_exhausted": "raise",
            },
        )
