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
from agent_actions.processing.types import ProcessingResult, ProcessingStatus
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.reasons import (
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
    DISPOSITION_SUCCESS,
    DISPOSITION_UNPROCESSED,
    NODE_LEVEL_RECORD_ID,
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


def _get_retry_attempts(result: ProcessingResult) -> str | int:
    """Extract retry attempt count from a result's recovery metadata.

    Returns the integer attempt count if available, otherwise ``"unknown"``.
    """
    if result.recovery_metadata and result.recovery_metadata.retry:
        return result.recovery_metadata.retry.attempts
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

    @property
    def only_guard_outcomes(self) -> bool:
        """True when every collected record was guard-skipped or guard-filtered.

        Uses ``dataclasses.fields()`` so that adding a new status field
        automatically makes this return False until the new field is
        accounted for — no manual update needed.
        """
        total: int = sum(getattr(self, f.name) for f in fields(self))
        return bool((self.skipped + self.filtered) == total)


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
    if not source or not isinstance(source, dict):
        return None
    try:
        return json.dumps(source, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        logger.debug("Could not serialize input snapshot: %s", type(source).__name__, exc_info=True)
        return None


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
    Clears any prior DEFERRED disposition for each record, then writes
    the final status (EXHAUSTED, FAILED, FILTERED, PASSTHROUGH).
    Success records only get their DEFERRED cleared — no new disposition.

    Disposition writes are telemetry — errors are logged but never propagated.
    """
    if not storage_backend:
        return
    for item in items:
        source_guid = item.get("source_guid")
        if not source_guid:
            continue
        metadata = item.get("metadata", {})

        try:
            # Clear the DEFERRED disposition now that the batch result has
            # arrived.  For success records this is the only disposition
            # action; for non-success records the final disposition is
            # written immediately below.
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

        # Check for evaluation/reprompt exhaustion via _recovery metadata.
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
            )
        elif metadata.get("retry_exhausted"):
            _safe_set_disposition(
                storage_backend,
                action_name,
                source_guid,
                DISPOSITION_EXHAUSTED,
                reason=RETRY_EXHAUSTED,
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
            _safe_set_disposition(
                storage_backend,
                action_name,
                source_guid,
                DISPOSITION_FAILED,
                reason=str(item["error"])[:500],
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
    ) -> tuple[list[dict[str, Any]], CollectionStats]:
        """Flatten ProcessingResult entries into output records.

        Returns:
            Tuple of (output_records, stats). Stats contain counts by status.

        Raises:
            AgentActionsError: If on_exhausted=raise and records exhausted retries.
        """
        fire_event(
            ResultCollectionStartedEvent(
                action_name=agent_name,
                total_results=len(results),
            )
        )

        ResultCollector._check_exhausted_raise(results, agent_config, agent_name, storage_backend)

        output: list[dict[str, Any]] = []
        stats: collections.Counter[str] = collections.Counter()

        for idx, result in enumerate(results):
            status = result.status
            status_key = status.value
            stats[status_key] += 1

            if status == ProcessingStatus.SUCCESS:
                data = result.data or []

                # Detect parse-error records masquerading as SUCCESS.
                # The LLM provider returns {"_parse_error": ...} on JSON
                # parse failure, which flows through as SUCCESS data.
                # Reprompt has already had its chance to repair (it runs
                # during invocation, before result collection).
                if data and _data_has_parse_error(data):
                    result.status = ProcessingStatus.FAILED
                    for d in data:
                        _stamp(d, RecordState.FAILED, agent_name, PARSE_ERROR)
                    output.extend(data)
                    stats[status_key] -= 1
                    stats["failed"] += 1
                    logger.warning(
                        "[%s] SUCCESS result source_guid=%s contains _parse_error "
                        "— dispositioned as FAILED",
                        agent_name,
                        result.source_guid,
                    )
                    fire_event(
                        ResultCollectedEvent(
                            action_name=agent_name,
                            result_index=idx,
                            status="failed",
                        )
                    )
                    if storage_backend and result.source_guid:
                        _safe_set_disposition(
                            storage_backend,
                            agent_name,
                            result.source_guid,
                            DISPOSITION_FAILED,
                            reason=PARSE_ERROR,
                        )
                    continue

                if data:
                    for d in data:
                        _stamp(d, RecordState.PROCESSED, agent_name, SUCCESS)
                    output.extend(data)
                logger.debug(
                    "Collected SUCCESS result source_guid=%s count=%d",
                    result.source_guid,
                    len(data),
                )
                fire_event(
                    ResultCollectedEvent(
                        action_name=agent_name,
                        result_index=idx,
                        status="success",
                    )
                )
                if storage_backend and result.source_guid:
                    _safe_set_disposition(
                        storage_backend,
                        agent_name,
                        result.source_guid,
                        DISPOSITION_SUCCESS,
                    )

            elif status == ProcessingStatus.SKIPPED:
                data = result.data or []
                if data:
                    for d in data:
                        _stamp(
                            d,
                            RecordState.GUARD_SKIPPED,
                            agent_name,
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
                        action_name=agent_name,
                        result_index=idx,
                        status="skipped",
                    )
                )
                if storage_backend and result.source_guid:
                    _safe_set_disposition(
                        storage_backend,
                        agent_name,
                        result.source_guid,
                        DISPOSITION_PASSTHROUGH,
                        reason=result.skip_reason or GUARD_SKIP,
                    )

            elif status == ProcessingStatus.EXHAUSTED:
                data = result.data or []
                if data:
                    for d in data:
                        _stamp(d, RecordState.EXHAUSTED, agent_name, RETRY_EXHAUSTED)
                    output.extend(data)
                attempts = _get_retry_attempts(result)
                logger.debug(
                    "Collected EXHAUSTED result source_guid=%s attempts=%s",
                    result.source_guid,
                    attempts,
                )
                fire_event(
                    ExhaustedRecordEvent(
                        action_name=agent_name,
                        record_index=idx,
                        source_guid=result.source_guid or "",
                        reason=f"exhausted_after_{attempts}_attempts",
                    )
                )
                if storage_backend and result.source_guid:
                    input_snapshot_str = _serialize_snapshot(
                        result.source_snapshot or result.input_record
                    )
                    _safe_set_disposition(
                        storage_backend,
                        agent_name,
                        result.source_guid,
                        DISPOSITION_EXHAUSTED,
                        reason=f"exhausted_after_{attempts}_attempts",
                        input_snapshot=input_snapshot_str,
                        detail=result.error,
                    )

            elif status == ProcessingStatus.FAILED:
                logger.error(
                    "[%s] Processing failed for source_guid=%s: %s",
                    agent_name,
                    result.source_guid,
                    result.error,
                )
                fire_event(
                    ResultCollectedEvent(
                        action_name=agent_name,
                        result_index=idx,
                        status="failed",
                    )
                )
                if storage_backend and result.source_guid:
                    input_snapshot_str = _serialize_snapshot(
                        result.source_snapshot or result.input_record
                    )
                    _safe_set_disposition(
                        storage_backend,
                        agent_name,
                        result.source_guid,
                        DISPOSITION_FAILED,
                        reason=result.error or "processing_error",
                        input_snapshot=input_snapshot_str,
                        detail=result.error,
                    )

            elif status == ProcessingStatus.FILTERED:
                logger.debug("Collected FILTERED result source_guid=%s", result.source_guid)
                fire_event(
                    ResultCollectedEvent(
                        action_name=agent_name,
                        result_index=idx,
                        status="filtered",
                    )
                )
                if storage_backend and result.source_guid:
                    _safe_set_disposition(
                        storage_backend,
                        agent_name,
                        result.source_guid,
                        DISPOSITION_FILTERED,
                        reason=result.skip_reason or GUARD_FILTER,
                    )

            elif status == ProcessingStatus.UNPROCESSED:
                data = result.data or []
                if data:
                    reason = result.skip_reason or UNPROCESSED
                    # FILE prefilter uses UNPROCESSED for ordering (FM13) but is a guard decision
                    state = (
                        RecordState.GUARD_SKIPPED
                        if reason in (GUARD_PREFILTER_SKIP, GUARD_SKIP, GUARD_FILTER)
                        else RecordState.CASCADE_SKIPPED
                    )
                    for d in data:
                        _stamp(d, state, agent_name, reason)
                    output.extend(data)  # Preserve in output for lineage
                logger.debug(
                    "Collected UNPROCESSED result source_guid=%s count=%d",
                    result.source_guid,
                    len(data),
                )
                fire_event(
                    ResultCollectedEvent(
                        action_name=agent_name,
                        result_index=idx,
                        status="unprocessed",
                    )
                )
                if storage_backend and result.source_guid:
                    _safe_set_disposition(
                        storage_backend,
                        agent_name,
                        result.source_guid,
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
                        action_name=agent_name,
                        result_index=idx,
                        status="deferred",
                    )
                )
                if storage_backend and result.source_guid:
                    _safe_set_disposition(
                        storage_backend,
                        agent_name,
                        result.source_guid,
                        DISPOSITION_DEFERRED,
                        reason=f"batch_queued:task_id={task_id}",
                    )

            else:
                logger.debug("Unhandled result status=%s", status)  # type: ignore[unreachable]

        guard_config = agent_config.get("guard", {})
        guard_condition = guard_config.get("clause", "") if isinstance(guard_config, dict) else ""
        guard_on_false = guard_config.get("behavior", "") if isinstance(guard_config, dict) else ""

        fire_event(
            ResultCollectionCompleteEvent(
                action_name=agent_name,
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
                "[%s] All %d records filtered by guard (%s). "
                "Downstream actions will receive no input.",
                agent_name,
                total_input,
                guard_condition or "unknown condition",
            )

        tombstone_count = stats["skipped"] + stats["exhausted"] + stats["unprocessed"]
        if tombstone_count > 0:
            logger.info(
                "[%s] %d/%d records are tombstones (skipped=%d, exhausted=%d, unprocessed=%d)",
                agent_name,
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
        )

    @staticmethod
    def _check_exhausted_raise(
        results: list[ProcessingResult],
        agent_config: dict[str, Any],
        agent_name: str,
        storage_backend: Optional["StorageBackend"],
    ) -> None:
        """Raise if on_exhausted=raise and any results exhausted retries."""
        exhausted_results = [r for r in results if r.status == ProcessingStatus.EXHAUSTED]
        if not exhausted_results:
            return

        retry_config = agent_config.get("retry", {})
        on_exhausted = retry_config.get("on_exhausted", "return_last")

        logger.warning(
            "[%s] %d records have exhausted retries (on_exhausted=%s)",
            agent_name,
            len(exhausted_results),
            on_exhausted,
        )

        if on_exhausted != "raise":
            return

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

        first = exhausted_results[0]
        raise AgentActionsError(
            f"Retry exhausted for record {first.source_guid} after "
            f"{_get_retry_attempts(first)} attempts (on_exhausted=raise)",
            context={
                "agent_name": agent_name,
                "exhausted_records": len(exhausted_results),
                "on_exhausted": "raise",
            },
        )
