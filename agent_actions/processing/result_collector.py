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
from agent_actions.record.state import RecordState, reason_error
from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_GUARD_FILTERED,
    DISPOSITION_GUARD_SKIPPED,
    DISPOSITION_CASCADE_SKIPPED,
    DISPOSITION_SUCCESS,
    NODE_LEVEL_RECORD_ID,
)

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


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


def _safe_set_disposition(
    backend: "StorageBackend",
    action_name: str,
    record_id: str,
    disposition: str,
    **kwargs: Any,
) -> None:
    """Write a disposition record, logging and swallowing errors.

    Disposition writes are telemetry — they must not crash the data pipeline.
    """
    try:
        backend.set_disposition(action_name, record_id, disposition, **kwargs)
    except Exception:
        logger.warning(
            "Failed to write disposition action=%s record=%s disp=%s",
            action_name,
            record_id,
            disposition,
            exc_info=True,
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

        state = RecordState.from_record(item)

        # Reprompt exhaustion is expressed via _recovery metadata, not record state.
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
            continue

        transitions = item.get("_transitions") if isinstance(item.get("_transitions"), list) else []
        last = transitions[-1] if transitions else {}
        reason_obj = last.get("reason")
        detail_obj = last.get("detail")
        reason_str = (
            json.dumps(reason_obj, ensure_ascii=False, default=str) if isinstance(reason_obj, dict) else None
        )
        detail_str = (
            json.dumps(detail_obj, ensure_ascii=False, default=str) if isinstance(detail_obj, dict) else None
        )

        if state == RecordState.EXHAUSTED:
            _safe_set_disposition(
                storage_backend,
                action_name,
                source_guid,
                DISPOSITION_EXHAUSTED,
                reason=reason_str,
                detail=detail_str,
            )
        elif state == RecordState.FAILED:
            _safe_set_disposition(
                storage_backend,
                action_name,
                source_guid,
                DISPOSITION_FAILED,
                reason=reason_str or (str(item.get("error"))[:500] if item.get("error") else None),
                detail=detail_str,
            )
        elif state == RecordState.CASCADE_SKIPPED:
            _safe_set_disposition(
                storage_backend,
                action_name,
                source_guid,
                DISPOSITION_CASCADE_SKIPPED,
                reason=reason_str,
                detail=detail_str,
            )
        elif state == RecordState.GUARD_SKIPPED:
            _safe_set_disposition(
                storage_backend,
                action_name,
                source_guid,
                DISPOSITION_GUARD_SKIPPED,
                reason=reason_str,
                detail=detail_str,
            )
        elif state == RecordState.GUARD_FILTERED:
            _safe_set_disposition(
                storage_backend,
                action_name,
                source_guid,
                DISPOSITION_GUARD_FILTERED,
                reason=reason_str,
                detail=detail_str,
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
                    for d in data:
                        if isinstance(d, dict):
                            RecordEnvelope.transition(
                                d,
                                RecordState.FAILED,
                                action_name=agent_name,
                                reason=reason_error(
                                    error_type="parse_error", message="LLM provider returned _parse_error"
                                ),
                            )
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
                            reason="parse_error",
                        )
                    continue

                if data:
                    for d in data:
                        if isinstance(d, dict):
                            RecordEnvelope.transition(
                                d,
                                RecordState.COMMITTED,
                                action_name=agent_name,
                                reason={"type": "commit"},
                            )
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
                        DISPOSITION_GUARD_SKIPPED,
                        reason=result.skip_reason or "guard_skipped",
                    )

            elif status == ProcessingStatus.EXHAUSTED:
                data = result.data or []
                if data:
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
                    _safe_set_disposition(
                        storage_backend,
                        agent_name,
                        result.source_guid,
                        DISPOSITION_EXHAUSTED,
                        reason=f"exhausted_after_{attempts}_attempts",
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
                    snapshot_source = result.source_snapshot or result.input_record
                    input_snapshot_str = None
                    if snapshot_source and isinstance(snapshot_source, dict):
                        try:
                            input_snapshot_str = json.dumps(
                                snapshot_source, ensure_ascii=False, default=str
                            )
                        except (TypeError, ValueError) as snap_err:
                            logger.debug(
                                "Could not serialize input snapshot for %s: %s",
                                result.source_guid,
                                snap_err,
                            )
                            input_snapshot_str = None
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
                        DISPOSITION_GUARD_FILTERED,
                        reason=result.skip_reason or "guard_filtered",
                    )

            elif status == ProcessingStatus.UNPROCESSED:
                data = result.data or []
                if data:
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
                    # Derive from the record state when available.
                    disp = DISPOSITION_CASCADE_SKIPPED
                    reason = result.skip_reason or "cascade_skipped"
                    if data and isinstance(data[0], dict):
                        s = RecordState.from_record(data[0])
                        if s == RecordState.FAILED:
                            disp = DISPOSITION_FAILED
                            reason = "failed"
                        elif s == RecordState.GUARD_SKIPPED:
                            disp = DISPOSITION_GUARD_SKIPPED
                            reason = "guard_skipped"
                    _safe_set_disposition(
                        storage_backend,
                        agent_name,
                        result.source_guid,
                        disp,
                        reason=reason,
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
                    _safe_set_disposition(
                        storage_backend,
                        agent_name,
                        er.source_guid,
                        DISPOSITION_EXHAUSTED,
                        reason=f"exhausted_after_{_get_retry_attempts(er)}_attempts",
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
