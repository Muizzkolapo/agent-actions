"""Legacy blocking methods for BatchRetryService (deprecated).

These functions were originally methods on BatchRetryService. They block via
``wait_for_batch_completion()`` polling and are only exercised by tests.
Production code uses the modern async methods on BatchRetryService directly.

Each extracted method takes ``service: BatchRetryService`` as its first
argument so it can access instance state (storage backend, agent indices, etc.).

Note: Functions that reference module-level names patched by tests on the
``retry`` module (``retrieve_and_reconcile``, ``_import_validation_module``,
``wait_for_batch_completion``) use lazy imports from ``retry`` to ensure
test patches are respected.
"""

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult
from agent_actions.logging import fire_event
from agent_actions.logging.events import BatchProgressEvent
from agent_actions.processing.types import RecoveryMetadata, RetryMetadata

if TYPE_CHECKING:
    from agent_actions.llm.batch.services.retry import BatchRetryService

logger = logging.getLogger(__name__)


def retrieve_results_with_retry(
    service: "BatchRetryService",
    provider: BaseBatchClient,
    batch_id: str,
    output_directory: str,
    *,
    context_map: dict[str, Any],
    record_count: int | None = None,
    file_name: str | None = None,
    agent_config: dict[str, Any] | None = None,
) -> tuple[list[BatchResult], dict[str, RecoveryMetadata] | None]:
    """Retrieve batch results with retry for missing records.

    DEPRECATED: This function blocks via wait_for_batch_completion().
    Use the async recovery path in BatchProcessingService instead.

    If retry is enabled and records are missing, resubmits missing records
    as a new batch and consolidates results.

    Args:
        service: BatchRetryService instance (provides storage backend and config)
        provider: Batch API client
        batch_id: Batch job ID
        output_directory: Output directory path
        context_map: Context map for reconciliation and record lookup
        record_count: Expected record count
        file_name: Original file name
        agent_config: Agent configuration with retry settings

    Returns:
        Tuple of (consolidated batch results, per-record recovery metadata for exhausted records)
        The dict maps custom_id -> RecoveryMetadata for records that never succeeded.
    """
    # Lazy import: tests patch this name on the retry module
    from agent_actions.llm.batch.services.retry import retrieve_and_reconcile

    retry_config = (agent_config or {}).get("retry")
    retry_enabled = retry_config and retry_config.get("enabled", True)
    max_attempts = retry_config.get("max_attempts", 3) if retry_config else 3

    all_results = retrieve_and_reconcile(
        provider,
        batch_id,
        output_directory,
        context_map=context_map,
        record_count=record_count,
        file_name=file_name,
    )

    # =========================================================================
    # PHASE 1: RETRY - Ensure we have all records we can get
    # =========================================================================
    exhausted_recovery: dict[str, RecoveryMetadata] | None = None

    if not retry_enabled:
        pass
    else:
        expected_ids = BatchResultReconciler.collect_expected_custom_ids(context_map)
        received_ids = BatchResultReconciler.collect_result_custom_ids(all_results)
        missing_ids = expected_ids - received_ids

        if not missing_ids:
            # All records received on first try - skip retry loop
            pass
        else:
            # Per-record failure tracking: each record tracks its own failure count
            # Initial failure = 1 (the initial batch didn't return this record)
            record_failure_counts: dict[str, int] = {rid: 1 for rid in missing_ids}

            retry_attempts = 0

            while missing_ids and retry_attempts < max_attempts:
                retry_attempts += 1
                logger.info(
                    "Batch retry attempt %d/%d: resubmitting %d missing records",
                    retry_attempts,
                    max_attempts,
                    len(missing_ids),
                )

                retry_results = service._resubmit_missing_records(
                    provider=provider,
                    missing_ids=missing_ids,
                    context_map=context_map,
                    output_directory=output_directory,
                    file_name=file_name,
                    agent_config=agent_config,
                )

                if retry_results:
                    for res in retry_results:
                        if res.success:
                            custom_id = res.custom_id
                            failures = record_failure_counts.get(custom_id, 1)
                            res.recovery_metadata = RecoveryMetadata(
                                retry=RetryMetadata(
                                    attempts=failures + 1,  # failures + 1 success
                                    failures=failures,
                                    succeeded=True,
                                    reason="missing",
                                    timestamp=datetime.now(UTC).isoformat(),
                                )
                            )

                    all_results.extend(retry_results)

                    # Only count *successful* results when updating missing IDs.
                    # Failed results should remain in missing_ids for further retries.
                    successful_retry = [r for r in retry_results if r.success]
                    new_received = BatchResultReconciler.collect_result_custom_ids(successful_retry)
                    missing_ids = missing_ids - new_received

                for rid in missing_ids:
                    record_failure_counts[rid] = record_failure_counts.get(rid, 0) + 1

            # Build per-record recovery metadata for exhausted records (still missing after all retries)
            # This is used by passthrough processing for records that never succeeded
            if retry_attempts > 0 and missing_ids:
                exhausted_recovery = {}
                for rid in missing_ids:
                    failures = record_failure_counts.get(rid, 1)
                    # For exhausted records: attempts = failures (no successful attempt to add)
                    exhausted_recovery[rid] = RecoveryMetadata(
                        retry=RetryMetadata(
                            attempts=failures,
                            failures=failures,
                            succeeded=False,
                            reason="missing",
                            timestamp=datetime.now(UTC).isoformat(),
                        )
                    )
                logger.warning(
                    "Batch retry exhausted: %d records still missing after %d attempts",
                    len(missing_ids),
                    retry_attempts,
                )

    # =========================================================================
    # PHASE 2: VALIDATE - Ensure all records meet validation conditions
    # =========================================================================
    all_results = service.validate_and_reprompt(
        results=all_results,
        provider=provider,
        context_map=context_map,
        output_directory=output_directory,
        file_name=file_name,
        agent_config=agent_config,
        agent_indices=service._agent_indices,
        dependency_configs=service._dependency_configs,
    )

    return all_results, exhausted_recovery


def _resubmit_missing_records(
    service: "BatchRetryService",
    provider: BaseBatchClient,
    missing_ids: set[str],
    context_map: dict[str, Any],
    output_directory: str,
    file_name: str | None,
    agent_config: dict[str, Any] | None,
) -> list[BatchResult]:
    """Resubmit missing records as a new batch and wait for completion.

    DEPRECATED: Blocks via wait_for_batch_completion().
    Use submit_retry_batch() for non-blocking submission.

    Args:
        service: BatchRetryService instance (provides storage backend)
        provider: Batch API client
        missing_ids: Set of custom_ids that are missing
        context_map: Context map with original record data
        output_directory: Output directory path
        file_name: Original file name
        agent_config: Agent configuration

    Returns:
        List of batch results from retry batch
    """
    from agent_actions.llm.batch.processing.preparator import (
        BatchTaskPreparator,
    )

    # Lazy import: tests patch this name on the retry module
    from agent_actions.llm.batch.services.retry import wait_for_batch_completion

    missing_records = []
    for custom_id in missing_ids:
        if custom_id in context_map:
            record = context_map[custom_id].copy()
            if "target_id" not in record:
                record["target_id"] = custom_id
            missing_records.append(record)

    if not missing_records:
        logger.warning("No records found in context_map for missing IDs")
        return []

    try:
        preparator = BatchTaskPreparator(storage_backend=service._storage_backend)
        prepared = preparator.prepare_tasks(
            agent_config=agent_config or {},
            data=missing_records,
            provider=provider,
            output_directory=output_directory,
            batch_name=f"{file_name}_retry" if file_name else "retry",
        )

        if not prepared.tasks:
            logger.warning("No tasks prepared for retry batch")
            return []

        batch_name = f"{file_name}_retry" if file_name else "retry"
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

        # Wait for completion (simple polling)
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


def validate_and_reprompt(
    service: "BatchRetryService",
    results: list[BatchResult],
    provider: BaseBatchClient,
    context_map: dict[str, Any],
    output_directory: str,
    file_name: str | None,
    agent_config: dict[str, Any] | None,
    agent_indices: dict[str, int] | None = None,
    dependency_configs: dict[str, dict] | None = None,
) -> list[BatchResult]:
    """Validate results and reprompt failures with feedback.

    DEPRECATED: Blocks via wait_for_batch_completion().
    Use validate_results() + submit_reprompt_batch() for non-blocking flow.

    Validates batch results using configured UDF. Records that fail validation
    are resubmitted with feedback messages appended to their prompts.

    Args:
        service: BatchRetryService instance (provides storage backend)
        results: Initial batch results to validate
        provider: Batch API client
        context_map: Context map for record lookup
        output_directory: Output directory path
        file_name: Original file name
        agent_config: Agent configuration with reprompt settings
        agent_indices: Dict mapping agent names to node indices (for dependency resolution)
        dependency_configs: Dict mapping dependency names to configs (for dependency resolution)

    Returns:
        Consolidated list of batch results (original passes + reprompt results)
    """
    from agent_actions.llm.batch.processing.preparator import (
        BatchTaskPreparator,
    )
    from agent_actions.llm.batch.services.retry import (
        _import_validation_module,
        wait_for_batch_completion,
    )
    from agent_actions.processing.recovery.response_validator import build_validation_feedback
    from agent_actions.processing.recovery.validation import get_validation_function
    from agent_actions.processing.types import RepromptMetadata
    from agent_actions.utils.tools_resolver import resolve_tools_path

    reprompt_config = (agent_config or {}).get("reprompt")
    logger.debug(
        "Batch reprompt check: agent_config has %d keys, reprompt_config=%s",
        len(agent_config or {}),
        reprompt_config,
    )
    if not reprompt_config:
        logger.debug("Reprompt not configured, skipping validation")
        return results

    validation_name = reprompt_config.get("validation")
    if not validation_name:
        logger.warning("Reprompt enabled but no validation UDF specified")
        return results

    max_attempts = reprompt_config.get("max_attempts", 2)
    on_exhausted = reprompt_config.get("on_exhausted", "return_last")

    validation_path = reprompt_config.get("validation_path")
    if not validation_path:
        validation_path = resolve_tools_path(agent_config or {})

    validation_module = reprompt_config.get("validation_module", "reprompt_validations")

    if validation_path:
        _import_validation_module(validation_module, validation_path)
    else:
        logger.debug(
            "No validation_path configured, attempting direct import of '%s'",
            validation_module,
        )
        _import_validation_module(validation_module, None)

    try:
        validation_func, feedback_message = get_validation_function(validation_name)
    except ValueError as e:
        logger.error("Failed to get validation function: %s", e)
        return results

    reprompt_attempts: dict[str, int] = {}
    validation_status: dict[str, bool] = {}
    result_map = {r.custom_id: r for r in results}

    attempt = 0
    while attempt < max_attempts:
        attempt += 1

        failed_results = []
        for result in result_map.values():
            if not result.success:
                continue

            # Skip if already passed
            if (
                result.recovery_metadata
                and result.recovery_metadata.reprompt
                and result.recovery_metadata.reprompt.passed
            ):
                continue

            try:
                is_valid = validation_func(result.content)
            except Exception as e:
                logger.warning(
                    "Validation UDF error for %s (treating as failure): %s",
                    result.custom_id,
                    e,
                    exc_info=True,
                )
                is_valid = False

            validation_status[result.custom_id] = is_valid

            if not is_valid:
                failed_results.append(result)

        if not failed_results:
            logger.info("All %d records passed validation", len(result_map))
            break

        logger.warning(
            "Reprompt attempt %d/%d: %d records failed validation",
            attempt,
            max_attempts,
            len(failed_results),
        )

        for failed_result in failed_results:
            reprompt_attempts[failed_result.custom_id] = (
                reprompt_attempts.get(failed_result.custom_id, 0) + 1
            )

        if attempt >= max_attempts:
            for failed_result in failed_results:
                if on_exhausted == "raise":
                    raise RuntimeError(
                        f"Reprompt validation exhausted for {failed_result.custom_id} "
                        f"after {attempt} attempts (validation: {validation_name})"
                    )

                if not failed_result.recovery_metadata:
                    failed_result.recovery_metadata = RecoveryMetadata()

                failed_result.recovery_metadata.reprompt = RepromptMetadata(
                    attempts=attempt,
                    passed=False,
                    validation=validation_name,
                )
            break

        reprompt_records = []
        for failed_result in failed_results:
            custom_id = failed_result.custom_id

            if custom_id not in context_map:
                logger.warning(
                    "Cannot reprompt %s: not found in context_map",
                    custom_id,
                )
                continue

            original_record = context_map[custom_id].copy()

            feedback = build_validation_feedback(
                failed_response=failed_result.content,
                feedback_message=feedback_message,
            )

            original_user_content = original_record.get("user_content", "")
            original_record["user_content"] = f"{original_user_content}\n\n{feedback}"

            if "target_id" not in original_record:
                original_record["target_id"] = custom_id

            reprompt_records.append(original_record)

        if not reprompt_records:
            logger.warning("No records to reprompt")
            break

        try:
            reprompt_batch_name = f"{file_name or 'batch'}_reprompt_{attempt}"
            preparator = BatchTaskPreparator(
                agent_indices=agent_indices or {},
                dependency_configs=dependency_configs or {},
                storage_backend=service._storage_backend,
            )
            prepared = preparator.prepare_tasks(
                agent_config=agent_config or {},
                data=reprompt_records,
                provider=provider,
                output_directory=output_directory,
                batch_name=reprompt_batch_name,
            )

            batch_id, status = provider.submit_batch(
                tasks=prepared.tasks,
                batch_name=reprompt_batch_name,
                output_directory=output_directory,
            )

            logger.info(
                "Submitted reprompt batch %s with %d records",
                batch_id,
                len(prepared.tasks),
            )

            final_status = wait_for_batch_completion(
                provider, batch_id, total_items=len(prepared.tasks)
            )

            if final_status != BatchStatus.COMPLETED:
                logger.error(
                    "Reprompt batch %s did not complete: %s",
                    batch_id,
                    final_status,
                )
                break

            reprompt_results = provider.retrieve_results(batch_id, output_directory)

            for reprompt_result in reprompt_results:
                if reprompt_result.custom_id in result_map:
                    existing_recovery = result_map[reprompt_result.custom_id].recovery_metadata

                    if not reprompt_result.recovery_metadata:
                        reprompt_result.recovery_metadata = RecoveryMetadata()

                    if existing_recovery and existing_recovery.retry:
                        reprompt_result.recovery_metadata.retry = existing_recovery.retry

                result_map[reprompt_result.custom_id] = reprompt_result

        except Exception as e:
            logger.exception("Error during reprompt batch submission: %s", e)
            break

    # validation_status is already up-to-date: the loop re-validates all results
    # (including reprompted ones) at the start of each iteration after merging.
    for custom_id, attempts in reprompt_attempts.items():
        if custom_id in result_map:
            result = result_map[custom_id]
            passed = validation_status.get(custom_id, False)

            if not result.recovery_metadata:
                result.recovery_metadata = RecoveryMetadata()

            result.recovery_metadata.reprompt = RepromptMetadata(
                attempts=attempts,
                passed=passed,
                validation=validation_name,
            )

    return list(result_map.values())


def wait_for_batch_completion(
    provider: BaseBatchClient,
    batch_id: str,
    timeout_seconds: int = 3600,
    poll_interval: int = 30,
    total_items: int = 0,
) -> BatchStatus:
    """Wait for batch to complete with polling.

    DEPRECATED: This function blocks the workflow. The async recovery path
    in BatchProcessingService should be used instead (#942).

    Fires BatchProgressEvent at intervals:
    - Every 10% completion
    - Every 60 seconds (whichever comes first)

    Args:
        provider: Batch API client
        batch_id: Batch job ID
        timeout_seconds: Maximum time to wait (default 1 hour)
        poll_interval: Seconds between status checks
        total_items: Total items in batch (for progress tracking)

    Returns:
        Final batch status
    """
    start_time = time.time()
    last_progress_time = start_time
    last_progress_pct = 0
    progress_interval = 60  # Fire progress event at least every 60 seconds

    while (time.time() - start_time) < timeout_seconds:
        status = provider.check_status(batch_id)

        # Try to get progress info from provider if available
        completed = 0
        failed = 0
        if hasattr(provider, "get_batch_progress"):
            try:
                progress = provider.get_batch_progress(batch_id)
                completed = progress.get("completed", 0)
                failed = progress.get("failed", 0)
            except Exception as e:
                logger.debug("Failed to get batch progress for %s: %s", batch_id, e, exc_info=True)

        current_pct = (completed / total_items * 100) if total_items > 0 else 0
        current_time = time.time()
        time_since_last_progress = current_time - last_progress_time

        # Fire progress event if:
        # - Progress increased by 10% or more
        # - 60 seconds have passed since last event
        should_fire_progress = (
            total_items > 0
            and (
                current_pct - last_progress_pct >= 10
                or time_since_last_progress >= progress_interval
            )
            and completed > 0
        )

        if should_fire_progress:
            fire_event(
                BatchProgressEvent(
                    batch_id=batch_id,
                    completed=completed,
                    total=total_items,
                    failed=failed,
                )
            )
            last_progress_time = current_time
            last_progress_pct = current_pct  # type: ignore[assignment]

        if status in (BatchStatus.COMPLETED, BatchStatus.FAILED, BatchStatus.CANCELLED):
            return status  # type: ignore[return-value]
        logger.debug("Retry batch %s status: %s, waiting...", batch_id, status)
        time.sleep(poll_interval)

    logger.warning("Retry batch %s timed out after %d seconds", batch_id, timeout_seconds)
    return provider.check_status(batch_id)  # type: ignore[return-value]
