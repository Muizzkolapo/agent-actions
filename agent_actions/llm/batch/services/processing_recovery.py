"""Recovery and finalization functions extracted from BatchProcessingService.

These are standalone functions that take a ``service: BatchProcessingService``
instance as their first argument.  Within this module the functions call each
other directly; methods that remain on the class are reached via ``service.*``.
"""

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)
from agent_actions.llm.batch.infrastructure.registry import (
    BatchRegistryManager,
)
from agent_actions.llm.batch.services.retry import BatchRetryService
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import BatchCompleteEvent
from agent_actions.processing.types import RecoveryMetadata
from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_SKIPPED,
)

if TYPE_CHECKING:
    from agent_actions.llm.batch.services.processing import BatchProcessingService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recovery batch orchestration
# ---------------------------------------------------------------------------


def process_recovery_batch(
    service: "BatchProcessingService",
    batch_id: str,
    file_name: str,
    entry: BatchJobEntry,
    output_directory: str,
    agent_config: dict[str, Any] | None,
    manager: BatchRegistryManager,
    action_name: str | None = None,
) -> str | None:
    """Process a recovery batch (retry or reprompt).

    Loads recovery state, merges new results, and determines next action.

    Returns:
        Output file path if processing is complete, None if more recovery is needed
    """
    start_time = time.time()
    parent_file_name = entry.parent_file_name
    if not parent_file_name:
        logger.error("Recovery entry %s has no parent_file_name", file_name)
        return None

    state = RecoveryStateManager.load(output_directory, parent_file_name)
    if not state:
        logger.error("No recovery state found for %s", parent_file_name)
        return None

    context_map = service._context_manager.load_batch_context_map(
        output_directory, parent_file_name
    )
    agent_config = service._apply_workflow_session_id(agent_config, entry)
    provider = service._client_resolver.get_for_batch_id(batch_id, manager, output_directory)

    recovery_results = retrieve_and_reconcile(
        provider,
        batch_id,
        output_directory,
        context_map=context_map,
        record_count=entry.record_count,
        file_name=file_name,
    )

    accumulated = BatchRetryService.deserialize_results(state.accumulated_results)

    if entry.recovery_type == "retry":
        return handle_retry_recovery(
            service,
            state=state,
            recovery_results=recovery_results,
            accumulated=accumulated,
            context_map=context_map,
            output_directory=output_directory,
            parent_file_name=parent_file_name,
            entry=entry,
            agent_config=agent_config,
            manager=manager,
            provider=provider,
            action_name=action_name,
            start_time=start_time,
        )
    elif entry.recovery_type == "reprompt":
        return handle_reprompt_recovery(
            service,
            state=state,
            recovery_results=recovery_results,
            accumulated=accumulated,
            context_map=context_map,
            output_directory=output_directory,
            parent_file_name=parent_file_name,
            entry=entry,
            agent_config=agent_config,
            manager=manager,
            provider=provider,
            action_name=action_name,
            start_time=start_time,
        )

    logger.error("Unknown recovery_type: %s", entry.recovery_type)
    return None


# ---------------------------------------------------------------------------
# Retry recovery
# ---------------------------------------------------------------------------


def handle_retry_recovery(
    service: "BatchProcessingService",
    state: RecoveryState,
    recovery_results: list[BatchResult],
    accumulated: list[BatchResult],
    context_map: dict[str, Any],
    output_directory: str,
    parent_file_name: str,
    entry: BatchJobEntry,
    agent_config: dict[str, Any] | None,
    manager: BatchRegistryManager,
    provider: Any,
    action_name: str | None,
    start_time: float,
) -> str | None:
    """Handle retry recovery batch completion."""
    missing_ids = set(state.missing_ids)

    merged, still_missing, updated_counts, _ = service._retry_service.process_retry_results(
        results=recovery_results,
        accumulated_results=accumulated,
        context_map=context_map,
        record_failure_counts=state.record_failure_counts,
        missing_ids=missing_ids,
    )

    if still_missing and state.retry_attempt < state.retry_max_attempts:
        next_attempt = state.retry_attempt + 1
        submission = service._retry_service.submit_retry_batch(
            provider=provider,
            missing_ids=still_missing,
            context_map=context_map,
            output_directory=output_directory,
            file_name=parent_file_name,
            agent_config=agent_config,
        )
        if submission:
            retry_batch_id, record_count = submission
            recovery_file_name = f"{parent_file_name}_retry_{next_attempt}"
            recovery_entry = BatchJobEntry(
                batch_id=retry_batch_id,
                status=BatchStatus.SUBMITTED,
                timestamp=datetime.now(UTC).isoformat(),
                provider=entry.provider,
                record_count=record_count,
                file_name=recovery_file_name,
                parent_file_name=parent_file_name,
                recovery_type="retry",
                recovery_attempt=next_attempt,
            )
            manager.save_batch_job(recovery_file_name, recovery_entry)

            state.retry_attempt = next_attempt
            state.missing_ids = list(still_missing)
            state.record_failure_counts = updated_counts
            state.accumulated_results = BatchRetryService.serialize_results(merged)
            RecoveryStateManager.save(output_directory, parent_file_name, state)
            return None  # More retries pending

    exhausted_recovery = None
    if still_missing:
        exhausted_recovery = service._retry_service.build_exhausted_recovery(
            still_missing, updated_counts
        )

    should_continue = check_and_submit_reprompt(
        service,
        batch_results=merged,
        context_map=context_map,
        output_directory=output_directory,
        file_name=parent_file_name,
        entry=entry,
        agent_config=agent_config,
        manager=manager,
        provider=provider,
        recovery_state=state,
        exhausted_recovery=exhausted_recovery,
    )
    if not should_continue:
        return None  # Reprompt submitted, processing paused

    RecoveryStateManager.delete(output_directory, parent_file_name)
    return finalize_batch_output(
        service,
        batch_results=merged,
        exhausted_recovery=exhausted_recovery,
        context_map=context_map,
        output_directory=output_directory,
        file_name=parent_file_name,
        batch_id=entry.batch_id,
        agent_config=agent_config,
        manager=manager,
        action_name=action_name,
        start_time=start_time,
    )


# ---------------------------------------------------------------------------
# Reprompt recovery
# ---------------------------------------------------------------------------


def handle_reprompt_recovery(
    service: "BatchProcessingService",
    state: RecoveryState,
    recovery_results: list[BatchResult],
    accumulated: list[BatchResult],
    context_map: dict[str, Any],
    output_directory: str,
    parent_file_name: str,
    entry: BatchJobEntry,
    agent_config: dict[str, Any] | None,
    manager: BatchRegistryManager,
    provider: Any,
    action_name: str | None,
    start_time: float,
) -> str | None:
    """Handle reprompt recovery batch completion."""
    merged = service._retry_service.process_reprompt_results(
        reprompt_results=recovery_results,
        accumulated_results=accumulated,
    )

    failed_results, validation_name = service._retry_service.validate_results(
        results=merged,
        agent_config=agent_config,
    )

    if failed_results and state.reprompt_attempt < state.reprompt_max_attempts:
        next_attempt = state.reprompt_attempt + 1
        submission = service._retry_service.submit_reprompt_batch(
            provider=provider,
            failed_results=failed_results,
            context_map=context_map,
            output_directory=output_directory,
            file_name=parent_file_name,
            agent_config=agent_config,
            attempt=next_attempt,
        )
        if submission:
            reprompt_batch_id, record_count = submission
            recovery_file_name = f"{parent_file_name}_reprompt_{next_attempt}"
            recovery_entry = BatchJobEntry(
                batch_id=reprompt_batch_id,
                status=BatchStatus.SUBMITTED,
                timestamp=datetime.now(UTC).isoformat(),
                provider=entry.provider,
                record_count=record_count,
                file_name=recovery_file_name,
                parent_file_name=parent_file_name,
                recovery_type="reprompt",
                recovery_attempt=next_attempt,
            )
            manager.save_batch_job(recovery_file_name, recovery_entry)

            for fr in failed_results:
                state.reprompt_attempts_per_record[fr.custom_id] = (
                    state.reprompt_attempts_per_record.get(fr.custom_id, 0) + 1
                )

            state.reprompt_attempt = next_attempt
            state.accumulated_results = BatchRetryService.serialize_results(merged)
            RecoveryStateManager.save(output_directory, parent_file_name, state)
            return None  # More reprompts pending

    if failed_results and validation_name:
        on_exhausted = state.on_exhausted
        failed_ids = {r.custom_id for r in failed_results}
        merged = service._retry_service.apply_exhausted_reprompt_metadata(
            results=merged,
            failed_ids=failed_ids,
            validation_name=validation_name,
            attempt=state.reprompt_attempt,
            on_exhausted=on_exhausted,
        )

    # Rebuild exhausted_recovery from state if retry had exhausted records.
    # Invariant: state.missing_ids and state.record_failure_counts are frozen
    # at the end of the retry phase (set in handle_retry_recovery or
    # check_and_submit_reprompt). The reprompt phase never modifies them —
    # it only tracks reprompt_attempts_per_record for validation failures.
    exhausted_recovery = None
    if state.missing_ids:
        exhausted_recovery = service._retry_service.build_exhausted_recovery(
            set(state.missing_ids), state.record_failure_counts
        )

    RecoveryStateManager.delete(output_directory, parent_file_name)
    return finalize_batch_output(
        service,
        batch_results=merged,
        exhausted_recovery=exhausted_recovery,
        context_map=context_map,
        output_directory=output_directory,
        file_name=parent_file_name,
        batch_id=entry.batch_id,
        agent_config=agent_config,
        manager=manager,
        action_name=action_name,
        start_time=start_time,
    )


# ---------------------------------------------------------------------------
# Reprompt check + submission
# ---------------------------------------------------------------------------


def check_and_submit_reprompt(
    service: "BatchProcessingService",
    batch_results: list[BatchResult],
    context_map: dict[str, Any],
    output_directory: str,
    file_name: str,
    entry: BatchJobEntry,
    agent_config: dict[str, Any] | None,
    manager: BatchRegistryManager,
    provider: Any,
    recovery_state: RecoveryState | None = None,
    exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
) -> bool:
    """Check if reprompt is needed and submit async batch if so.

    Returns:
        True if processing should continue (no reprompt, or reprompt exhausted/failed).
        False if a reprompt batch was submitted (caller should return None).
    """
    reprompt_config = (agent_config or {}).get("reprompt")
    if not reprompt_config:
        return True

    failed_results, validation_name = service._retry_service.validate_results(
        results=batch_results,
        agent_config=agent_config,
    )

    if not failed_results:
        return True

    max_attempts = reprompt_config.get("max_attempts", 2)
    on_exhausted = reprompt_config.get("on_exhausted", "return_last")

    current_attempt = 0
    if recovery_state:
        current_attempt = recovery_state.reprompt_attempt

    if current_attempt >= max_attempts:
        failed_ids = {r.custom_id for r in failed_results}
        service._retry_service.apply_exhausted_reprompt_metadata(
            results=batch_results,
            failed_ids=failed_ids,
            validation_name=validation_name or "",
            attempt=current_attempt,
            on_exhausted=on_exhausted,
        )
        return True

    next_attempt = current_attempt + 1
    submission = service._retry_service.submit_reprompt_batch(
        provider=provider,
        failed_results=failed_results,
        context_map=context_map,
        output_directory=output_directory,
        file_name=file_name,
        agent_config=agent_config,
        attempt=next_attempt,
    )

    if not submission:
        return True  # Submission failed, continue with current results

    reprompt_batch_id, record_count = submission
    recovery_file_name = f"{file_name}_reprompt_{next_attempt}"
    recovery_entry = BatchJobEntry(
        batch_id=reprompt_batch_id,
        status=BatchStatus.SUBMITTED,
        timestamp=datetime.now(UTC).isoformat(),
        provider=entry.provider,
        record_count=record_count,
        file_name=recovery_file_name,
        parent_file_name=file_name,
        recovery_type="reprompt",
        recovery_attempt=next_attempt,
    )
    manager.save_batch_job(recovery_file_name, recovery_entry)

    state = recovery_state or RecoveryState(phase="reprompt")
    state.phase = "reprompt"
    state.reprompt_attempt = next_attempt
    state.reprompt_max_attempts = max_attempts
    state.validation_name = validation_name
    state.on_exhausted = on_exhausted
    for fr in failed_results:
        state.reprompt_attempts_per_record[fr.custom_id] = (
            state.reprompt_attempts_per_record.get(fr.custom_id, 0) + 1
        )
    state.accumulated_results = BatchRetryService.serialize_results(batch_results)

    if exhausted_recovery:
        state.missing_ids = list(exhausted_recovery.keys())
        state.record_failure_counts = {
            rid: meta.retry.failures for rid, meta in exhausted_recovery.items() if meta.retry
        }

    RecoveryStateManager.save(output_directory, file_name, state)
    logger.info(
        "Async reprompt submitted for %s: %d failed records, batch %s",
        file_name,
        len(failed_results),
        reprompt_batch_id,
    )
    return False  # Recovery pending — caller should return None


# ---------------------------------------------------------------------------
# Output finalization
# ---------------------------------------------------------------------------


def finalize_batch_output(
    service: "BatchProcessingService",
    batch_results: list[BatchResult],
    exhausted_recovery: dict[str, RecoveryMetadata] | None,
    context_map: dict[str, Any],
    output_directory: str,
    file_name: str,
    batch_id: str,
    agent_config: dict[str, Any] | None,
    manager: BatchRegistryManager,
    action_name: str | None,
    start_time: float,
) -> str:
    """Finalize batch processing: convert, write output, fire events."""
    processed_data = service._convert_batch_results_to_workflow_format(
        batch_results,
        context_map=context_map,
        output_directory=output_directory,
        agent_config=agent_config,
        exhausted_recovery=exhausted_recovery,
    )

    if service._storage_backend and service._action_name:
        write_record_dispositions(service, processed_data, service._action_name)
        service._update_prompt_trace_responses(processed_data, service._action_name)

    output_file = service._determine_output_path(output_directory, file_name, batch_id)
    service._write_batch_output(output_file, processed_data, output_directory, action_name)

    elapsed_time = time.time() - start_time
    total_count = len(batch_results)
    successful_count = sum(1 for r in batch_results if r.success)
    failed_count = total_count - successful_count

    fire_event(
        BatchCompleteEvent(
            batch_id=batch_id,
            action_name=file_name or "default",
            total=total_count,
            completed=successful_count,
            failed=failed_count,
            elapsed_time=elapsed_time,
        )
    )

    manager.update_status(batch_id, BatchStatus.COMPLETED)
    service._cleanup_recovery_entries(manager, file_name)

    return str(output_file)


# ---------------------------------------------------------------------------
# Record dispositions
# ---------------------------------------------------------------------------


def write_record_dispositions(
    service: "BatchProcessingService",
    items: list[dict[str, Any]],
    action_name: str,
) -> None:
    """Write dispositions for non-success records in batch output.

    Called from both process_batch_results() (single-batch legacy API) and
    finalize_batch_output() (multi-batch collection path).  These are
    mutually exclusive entry points — a given batch never flows through both.

    Also clears any prior DEFERRED disposition for each record, since the
    batch result represents the final status (ARCH-003).

    Disposition writes are telemetry — errors are logged but never propagated.
    """
    if not service._storage_backend:
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
            service._storage_backend.clear_disposition(
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

        try:
            if metadata.get("retry_exhausted"):
                service._storage_backend.set_disposition(
                    action_name,
                    source_guid,
                    DISPOSITION_EXHAUSTED,
                    reason="retry_exhausted",
                )
            elif item.get("_unprocessed"):
                reason = metadata.get("reason", "unprocessed")
                if metadata.get("skipped_by_where_clause"):
                    disposition = DISPOSITION_FILTERED
                else:
                    disposition = DISPOSITION_SKIPPED
                service._storage_backend.set_disposition(
                    action_name,
                    source_guid,
                    disposition,
                    reason=reason,
                )
            elif item.get("error"):
                service._storage_backend.set_disposition(
                    action_name,
                    source_guid,
                    DISPOSITION_FAILED,
                    reason=str(item["error"])[:500],
                )
        except Exception:
            logger.warning(
                "Failed to write disposition for record %s",
                source_guid,
                exc_info=True,
            )
