"""Shared result aggregation for processing output records."""

import collections
import json
import logging
from dataclasses import dataclass
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
from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_SKIPPED,
    DISPOSITION_UNPROCESSED,
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
                if data:
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
                        DISPOSITION_SKIPPED,
                        reason=result.skip_reason or "guard_skip",
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
                        reason=result.skip_reason or "guard_filter",
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
                    _safe_set_disposition(
                        storage_backend,
                        agent_name,
                        result.source_guid,
                        DISPOSITION_UNPROCESSED,
                        reason=result.skip_reason or "unprocessed",
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
