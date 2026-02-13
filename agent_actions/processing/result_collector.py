"""Shared result aggregation for processing output records."""

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agent_actions.processing.types import ProcessingResult, ProcessingStatus
from agent_actions.errors import AgentActionsException
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    ResultCollectionStartedEvent,
    ResultCollectedEvent,
    ResultCollectionCompleteEvent,
    ExhaustedRecordEvent,
)
from agent_actions.storage.backend import (
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_SKIPPED,
    DISPOSITION_UNPROCESSED,
)

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


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
        results: List[ProcessingResult],
        agent_config: Dict[str, Any],
        agent_name: str,
        *,
        is_first_stage: bool,
        storage_backend: Optional["StorageBackend"] = None,
    ) -> List[Dict[str, Any]]:
        """
        Flatten ProcessingResult entries into output records.

        Args:
            results: Processing results to aggregate.
            agent_config: Agent configuration for schema hints.
            agent_name: Agent name for exhausted record lineage.
            is_first_stage: True for staging, False for downstream.
            storage_backend: Optional storage backend for writing per-record dispositions.
        Returns:
            List of output records.
        Raises:
            AgentActionsException: If on_exhausted=raise and records exhausted retries.
        """
        # Fire RC001: Result collection started
        fire_event(
            ResultCollectionStartedEvent(
                agent_name=agent_name,
                total_results=len(results),
            )
        )

        # Check on_exhausted config for raise behavior
        exhausted_results = [r for r in results if r.status == ProcessingStatus.EXHAUSTED]

        if exhausted_results:
            retry_config = agent_config.get("retry", {})
            on_exhausted = retry_config.get("on_exhausted", "return_last")

            logger.warning(
                "[%s] %d records have exhausted retries (on_exhausted=%s)",
                agent_name,
                len(exhausted_results),
                on_exhausted,
            )

            if on_exhausted == "raise":
                # Write dispositions for all exhausted records before raising
                if storage_backend:
                    for er in exhausted_results:
                        if er.source_guid:
                            er_attempts = (
                                er.recovery_metadata.retry.attempts
                                if er.recovery_metadata and er.recovery_metadata.retry
                                else "unknown"
                            )
                            _safe_set_disposition(
                                storage_backend,
                                agent_name,
                                er.source_guid,
                                DISPOSITION_EXHAUSTED,
                                reason=f"exhausted_after_{er_attempts}_attempts",
                            )

                exhausted_record = exhausted_results[0]
                attempts = (
                    exhausted_record.recovery_metadata.retry.attempts
                    if exhausted_record.recovery_metadata
                    and exhausted_record.recovery_metadata.retry
                    else "unknown"
                )
                raise AgentActionsException(
                    f"Retry exhausted for record {exhausted_record.source_guid} after "
                    f"{attempts} attempts (on_exhausted=raise)",
                    context={
                        "agent_name": agent_name,
                        "exhausted_records": len(exhausted_results),
                        "on_exhausted": "raise",
                    },
                )

        output: List[Dict[str, Any]] = []

        # Track statistics for RC003
        success_count = 0
        skipped_count = 0
        filtered_count = 0
        failed_count = 0
        exhausted_count = 0
        unprocessed_count = 0

        for idx, result in enumerate(results):
            if result.status == ProcessingStatus.SUCCESS:
                success_count += 1
                data = result.data or []
                if data:
                    output.extend(data)
                logger.debug(
                    "Collected SUCCESS result source_guid=%s count=%d",
                    result.source_guid,
                    len(data),
                )
                # Fire RC002: Result collected
                fire_event(
                    ResultCollectedEvent(
                        agent_name=agent_name,
                        result_index=idx,
                        status="success",
                    )
                )
            elif result.status == ProcessingStatus.SKIPPED:
                skipped_count += 1
                data = result.data or []
                if data:
                    output.extend(data)
                logger.debug(
                    "Collected SKIPPED result source_guid=%s count=%d",
                    result.source_guid,
                    len(data),
                )
                # Fire RC002: Result collected
                fire_event(
                    ResultCollectedEvent(
                        agent_name=agent_name,
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
            elif result.status == ProcessingStatus.EXHAUSTED:
                exhausted_count += 1
                data = result.data or []
                if data:
                    output.extend(data)
                attempts = (
                    result.recovery_metadata.retry.attempts
                    if result.recovery_metadata and result.recovery_metadata.retry
                    else "unknown"
                )
                logger.debug(
                    "Collected EXHAUSTED result source_guid=%s attempts=%s",
                    result.source_guid,
                    attempts,
                )
                # Fire RC004: Exhausted record event
                fire_event(
                    ExhaustedRecordEvent(
                        agent_name=agent_name,
                        record_index=idx,
                        source_guid=result.source_guid,
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
            elif result.status == ProcessingStatus.FAILED:
                failed_count += 1
                logger.error("Processing failed: %s", result.error)
                # Fire RC002: Result collected
                fire_event(
                    ResultCollectedEvent(
                        agent_name=agent_name,
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
                        reason=result.error or "processing_error",
                    )
            elif result.status == ProcessingStatus.FILTERED:
                filtered_count += 1
                logger.debug("Collected FILTERED result source_guid=%s", result.source_guid)
                # Fire RC002: Result collected
                fire_event(
                    ResultCollectedEvent(
                        agent_name=agent_name,
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
            elif result.status == ProcessingStatus.UNPROCESSED:
                unprocessed_count += 1
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
                        agent_name=agent_name,
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
            else:
                logger.debug("Unhandled result status=%s", result.status)

        # Fire RC003: Result collection complete with statistics
        fire_event(
            ResultCollectionCompleteEvent(
                agent_name=agent_name,
                total_success=success_count,
                total_skipped=skipped_count,
                total_filtered=filtered_count,
                total_failed=failed_count,
                total_exhausted=exhausted_count,
                total_unprocessed=unprocessed_count,
            )
        )

        # Log tombstone summary (dead records quarantined from downstream processing)
        tombstone_count = skipped_count + exhausted_count + unprocessed_count
        if tombstone_count > 0:
            total = len(results)
            logger.info(
                "[%s] %d/%d records are tombstones (skipped=%d, exhausted=%d, unprocessed=%d)",
                agent_name,
                tombstone_count,
                total,
                skipped_count,
                exhausted_count,
                unprocessed_count,
            )

        return output
