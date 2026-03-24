"""Retry operations for missing batch record recovery."""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.batch.services.retry_polling import wait_for_batch_completion
from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult
from agent_actions.processing.types import RecoveryMetadata, RetryMetadata

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


def _collect_missing_records(
    missing_ids: set[str],
    context_map: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build record dicts for IDs missing from the batch results."""
    records = []
    for custom_id in missing_ids:
        if custom_id in context_map:
            record = context_map[custom_id].copy()
            if "target_id" not in record:
                record["target_id"] = custom_id
            records.append(record)
    return records


def submit_retry_batch(
    storage_backend: "StorageBackend | None",
    provider: BaseBatchClient,
    missing_ids: set[str],
    context_map: dict[str, Any],
    output_directory: str,
    file_name: str | None,
    agent_config: dict[str, Any] | None,
) -> tuple[str, int] | None:
    """Submit a retry batch for missing records without blocking.

    Unlike resubmit_missing_records, this returns immediately after
    submission — no polling/waiting.

    Args:
        storage_backend: Optional storage backend for task preparation
        provider: Batch API client
        missing_ids: Set of custom_ids that are missing
        context_map: Context map with original record data
        output_directory: Output directory path
        file_name: Original file name
        agent_config: Agent configuration

    Returns:
        Tuple of (batch_id, record_count) if submitted, None if nothing to submit
    """
    from agent_actions.llm.batch.processing.preparator import (
        BatchTaskPreparator,
    )

    missing_records = _collect_missing_records(missing_ids, context_map)
    if not missing_records:
        logger.warning("No records found in context_map for missing IDs")
        return None

    try:
        batch_name = f"{file_name}_retry" if file_name else "retry"
        preparator = BatchTaskPreparator(storage_backend=storage_backend)
        prepared = preparator.prepare_tasks(
            agent_config=agent_config or {},
            data=missing_records,
            provider=provider,
            output_directory=output_directory,
            batch_name=batch_name,
        )

        if not prepared.tasks:
            logger.warning("No tasks prepared for retry batch")
            return None

        retry_batch_id, _ = provider.submit_batch(
            tasks=prepared.tasks,
            batch_name=batch_name,
            output_directory=output_directory,
        )
        logger.info(
            "Async retry batch submitted: %s with %d records",
            retry_batch_id,
            len(prepared.tasks),
        )
        return (retry_batch_id, len(prepared.tasks))

    except Exception as e:
        logger.warning("Failed to submit retry batch: %s", e, exc_info=True)
        return None


def resubmit_missing_records(
    storage_backend: "StorageBackend | None",
    provider: BaseBatchClient,
    missing_ids: set[str],
    context_map: dict[str, Any],
    output_directory: str,
    file_name: str | None,
    agent_config: dict[str, Any] | None,
) -> list[BatchResult]:
    """Resubmit missing records as a new batch and wait for completion."""
    from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator

    missing_records = _collect_missing_records(missing_ids, context_map)
    if not missing_records:
        logger.warning("No records found in context_map for missing IDs")
        return []

    try:
        batch_name = f"{file_name}_retry" if file_name else "retry"
        preparator = BatchTaskPreparator(storage_backend=storage_backend)
        prepared = preparator.prepare_tasks(
            agent_config=agent_config or {},
            data=missing_records,
            provider=provider,
            output_directory=output_directory,
            batch_name=batch_name,
        )

        if not prepared.tasks:
            logger.warning("No tasks prepared for retry batch")
            return []

        retry_batch_id, _ = provider.submit_batch(
            tasks=prepared.tasks,
            batch_name=batch_name,
            output_directory=output_directory,
        )
        logger.info(
            "Retry batch submitted: %s with %d records",
            retry_batch_id,
            len(prepared.tasks),
        )

        status = wait_for_batch_completion(
            provider, retry_batch_id, total_items=len(prepared.tasks)
        )
        if status != BatchStatus.COMPLETED:
            logger.warning(
                "Retry batch %s did not complete successfully: %s",
                retry_batch_id,
                status,
            )
            return []

        return provider.retrieve_results(retry_batch_id, output_directory)

    except Exception as e:
        logger.warning("Failed to resubmit missing records: %s", e, exc_info=True)
        return []


def process_retry_results(
    results: list[BatchResult],
    accumulated_results: list[BatchResult],
    context_map: dict[str, Any],
    record_failure_counts: dict[str, int],
    missing_ids: set[str],
) -> tuple[list[BatchResult], set[str], dict[str, int], dict[str, RecoveryMetadata] | None]:
    """Process retry batch results and determine if more retries are needed.

    Args:
        results: Results from the retry batch
        accumulated_results: Previously accumulated results
        context_map: Context map for expected ID checking
        record_failure_counts: Per-record failure counts
        missing_ids: IDs that were missing before this retry

    Returns:
        Tuple of (merged_results, still_missing_ids, updated_failure_counts, exhausted_recovery)
        exhausted_recovery is non-None only if retries are exhausted.
    """
    all_results = list(accumulated_results)

    if results:
        for res in results:
            if res.success:
                custom_id = res.custom_id
                failures = record_failure_counts.get(custom_id, 1)
                res.recovery_metadata = RecoveryMetadata(
                    retry=RetryMetadata(
                        attempts=failures + 1,
                        failures=failures,
                        succeeded=True,
                        reason="missing",
                        timestamp=datetime.now(UTC).isoformat(),
                    )
                )

        all_results.extend(results)

        successful_retry = [r for r in results if r.success]
        new_received = BatchResultReconciler.collect_result_custom_ids(successful_retry)
        missing_ids = missing_ids - new_received

    updated_counts = dict(record_failure_counts)
    for rid in missing_ids:
        updated_counts[rid] = updated_counts.get(rid, 0) + 1

    return all_results, missing_ids, updated_counts, None


def build_exhausted_recovery(
    missing_ids: set[str],
    record_failure_counts: dict[str, int],
    retry_attempts: int = 0,
) -> dict[str, RecoveryMetadata]:
    """Build recovery metadata for records that exhausted all retry attempts.

    Args:
        missing_ids: IDs still missing after all retries
        record_failure_counts: Per-record failure counts
        retry_attempts: Number of retry attempts made (for logging)

    Returns:
        Dict mapping custom_id -> RecoveryMetadata for exhausted records
    """
    exhausted_recovery: dict[str, RecoveryMetadata] = {}
    for rid in missing_ids:
        failures = record_failure_counts.get(rid, 1)
        exhausted_recovery[rid] = RecoveryMetadata(
            retry=RetryMetadata(
                attempts=failures,
                failures=failures,
                succeeded=False,
                reason="missing",
                timestamp=datetime.now(UTC).isoformat(),
            )
        )
    if retry_attempts:
        logger.warning(
            "Batch retry exhausted: %d records still missing after %d attempts",
            len(missing_ids),
            retry_attempts,
        )
    else:
        logger.warning(
            "Batch retry exhausted: %d records still missing",
            len(missing_ids),
        )
    return exhausted_recovery
