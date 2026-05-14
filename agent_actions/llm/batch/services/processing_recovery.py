"""Async recovery orchestration for batch processing.

State machine:
    Initial batch → retry (if missing_ids) → reprompt (if configured) → finalize

Entry points:
    process_recovery_batch() — dispatches on recovery_type
    check_and_submit_reprompt() — initial evaluation + reprompt submission
    finalize_batch_output() — convert, write, event, status
    cleanup_recovery() — remove registry entries after finalization
"""

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

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
from agent_actions.logging.events.validation_events import (
    RepromptRecoveredEvent,
    RepromptRetryEvent,
)
from agent_actions.processing.result_collector import write_record_dispositions
from agent_actions.processing.types import RecoveryMetadata
from agent_actions.record.envelope import RecordEnvelope

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

    Returns output file path if complete, None if more recovery is needed.
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
    provider = service._client_resolver.get_for_batch_id(
        batch_id, manager, output_directory, agent_config=agent_config
    )

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
    merged, still_missing, updated_counts, _ = service._retry_service.process_retry_results(
        results=recovery_results,
        accumulated_results=accumulated,
        context_map=context_map,
        record_failure_counts=state.record_failure_counts,
        missing_ids=set(state.missing_ids),
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
            _register_recovery_batch(
                manager, submission, parent_file_name, entry.provider, "retry", next_attempt
            )
            state.retry_attempt = next_attempt
            state.missing_ids = list(still_missing)
            state.record_failure_counts = updated_counts
            state.accumulated_results = BatchRetryService.serialize_results(merged)
            RecoveryStateManager.save(output_directory, parent_file_name, state)
            return None

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
        return None

    return _finalize_and_cleanup(
        service,
        merged,
        exhausted_recovery,
        context_map,
        output_directory,
        parent_file_name,
        entry.batch_id,
        agent_config,
        manager,
        action_name,
        start_time,
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
    """Handle reprompt recovery batch completion.

    Uses the graduated pool pattern: only recovery_results are evaluated
    (never the full accumulated set). Graduated records are persisted to
    state and never re-evaluated.
    """
    from agent_actions.llm.batch.services.reprompt_ops import build_evaluation_loop

    setup = build_evaluation_loop(
        agent_config,
        max_attempts=state.reprompt_max_attempts,
        on_exhausted=state.on_exhausted,
    )
    if setup is None:
        # Merge prior graduated results with current cycle before finalizing.
        final_results = BatchRetryService.deserialize_results(state.graduated_results)
        final_results.extend(recovery_results)
        return _finalize_and_cleanup(
            service,
            final_results,
            None,
            context_map,
            output_directory,
            parent_file_name,
            entry.batch_id,
            agent_config,
            manager,
            action_name,
            start_time,
        )

    loop, strategy, _ = setup
    graduated, still_failing = loop.split(recovery_results)
    loop.tag_graduated(graduated)
    state.graduated_results.extend(BatchRetryService.serialize_results(graduated))
    state.evaluation_strategy_name = strategy.name

    if still_failing and state.reprompt_attempt < state.reprompt_max_attempts:
        next_attempt = state.reprompt_attempt + 1
        submission = service._retry_service.submit_reprompt_batch(
            provider=provider,
            failed_results=still_failing,
            context_map=context_map,
            output_directory=output_directory,
            file_name=parent_file_name,
            agent_config=agent_config,
            attempt=next_attempt,
        )
        if submission:
            _register_recovery_batch(
                manager, submission, parent_file_name, entry.provider, "reprompt", next_attempt
            )
            fire_event(
                RepromptRetryEvent(
                    action_name=parent_file_name or "batch",
                    attempt=next_attempt,
                    max_attempts=state.reprompt_max_attempts,
                    error=f"{len(still_failing)} records failed validation",
                    failed_count=len(still_failing),
                )
            )
            for fr in still_failing:
                state.reprompt_attempts_per_record[fr.custom_id] = (
                    state.reprompt_attempts_per_record.get(fr.custom_id, 0) + 1
                )
            state.reprompt_attempt = next_attempt
            RecoveryStateManager.save(output_directory, parent_file_name, state)
            return None

    # Exhausted or all graduated — finalize.
    if still_failing:
        failed_ids = {r.custom_id for r in still_failing}
        service._retry_service.apply_exhausted_reprompt_metadata(
            results=still_failing,
            failed_ids=failed_ids,
            validation_name=strategy.name,
            attempt=state.reprompt_attempt,
            on_exhausted=state.on_exhausted,
        )

    final_results = BatchRetryService.deserialize_results(state.graduated_results)
    if still_failing:
        final_results.extend(still_failing)

    if state.graduated_results:
        fire_event(
            RepromptRecoveredEvent(
                action_name=parent_file_name or "batch",
                attempt=state.reprompt_attempt,
                max_attempts=state.reprompt_max_attempts,
                validation_name=strategy.name,
            )
        )

    # Rebuild exhausted_recovery from retry phase state (frozen at phase transition).
    exhausted_recovery = None
    if state.missing_ids:
        exhausted_recovery = service._retry_service.build_exhausted_recovery(
            set(state.missing_ids), state.record_failure_counts
        )

    return _finalize_and_cleanup(
        service,
        final_results,
        exhausted_recovery,
        context_map,
        output_directory,
        parent_file_name,
        entry.batch_id,
        agent_config,
        manager,
        action_name,
        start_time,
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
        True if processing should continue (no reprompt needed or exhausted).
        False if a reprompt batch was submitted (caller should return None).
    """
    from agent_actions.llm.batch.services.reprompt_ops import build_evaluation_loop

    setup = build_evaluation_loop(agent_config)
    if setup is None:
        return True

    loop, strategy, _ = setup
    max_attempts = strategy.max_attempts
    on_exhausted = strategy.on_exhausted

    graduated, still_failing = loop.split(batch_results)
    loop.tag_graduated(graduated)

    # Filter out records with None content (provider failures, not content quality issues)
    repromptable = [r for r in still_failing if r.content is not None]

    if not repromptable:
        return True

    current_attempt = recovery_state.reprompt_attempt if recovery_state else 0

    if current_attempt >= max_attempts:
        failed_ids = {r.custom_id for r in still_failing}
        service._retry_service.apply_exhausted_reprompt_metadata(
            results=still_failing,
            failed_ids=failed_ids,
            validation_name=strategy.name,
            attempt=current_attempt,
            on_exhausted=on_exhausted,
        )
        return True

    next_attempt = current_attempt + 1
    submission = service._retry_service.submit_reprompt_batch(
        provider=provider,
        failed_results=repromptable,
        context_map=context_map,
        output_directory=output_directory,
        file_name=file_name,
        agent_config=agent_config,
        attempt=next_attempt,
    )

    if not submission:
        return True

    _register_recovery_batch(
        manager, submission, file_name, entry.provider, "reprompt", next_attempt
    )

    state = RecoveryState(
        phase="reprompt",
        reprompt_attempt=next_attempt,
        reprompt_max_attempts=max_attempts,
        validation_name=strategy.name,
        on_exhausted=on_exhausted,
        evaluation_strategy_name=strategy.name,
        graduated_results=(list(recovery_state.graduated_results) if recovery_state else [])
        + BatchRetryService.serialize_results(graduated),
        reprompt_attempts_per_record=(
            dict(recovery_state.reprompt_attempts_per_record) if recovery_state else {}
        ),
        retry_attempt=recovery_state.retry_attempt if recovery_state else 0,
        retry_max_attempts=recovery_state.retry_max_attempts if recovery_state else 3,
        accumulated_results=list(recovery_state.accumulated_results) if recovery_state else [],
    )
    for fr in repromptable:
        state.reprompt_attempts_per_record[fr.custom_id] = (
            state.reprompt_attempts_per_record.get(fr.custom_id, 0) + 1
        )

    if exhausted_recovery:
        state.missing_ids = list(exhausted_recovery.keys())
        state.record_failure_counts = {
            rid: meta.retry.failures for rid, meta in exhausted_recovery.items() if meta.retry
        }

    RecoveryStateManager.save(output_directory, file_name, state)
    fire_event(
        RepromptRetryEvent(
            action_name=file_name or "batch",
            attempt=next_attempt,
            max_attempts=max_attempts,
            error=f"{len(still_failing)} records failed validation",
            failed_count=len(still_failing),
        )
    )
    logger.info(
        "Async reprompt submitted for %s: %d failed records, batch %s",
        file_name,
        len(repromptable),
        submission[0],
    )
    return False


# ---------------------------------------------------------------------------
# Finalization + cleanup
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

    effective_action_name = action_name if action_name is not None else service._action_name

    # Stamp _state on batch records before writing — batch results bypass the
    # online ResultCollector._stamp() path and arrive without lifecycle fields.
    _stamp_batch_records(processed_data, effective_action_name or file_name)

    if service._storage_backend and effective_action_name:
        write_record_dispositions(service._storage_backend, processed_data, effective_action_name)
        service._update_prompt_trace_responses(processed_data, effective_action_name)

    output_file = service._determine_output_path(output_directory, file_name, batch_id)
    service._write_batch_output(output_file, processed_data, output_directory, action_name)

    # Remove batch placeholder file if storage backend wrote to SQLite instead.
    # The placeholder (written at batch submission) persists on disk when
    # write_target goes to the backend, causing downstream reads to hit it.
    output_path = Path(output_file) if not isinstance(output_file, Path) else output_file
    if service._storage_backend and output_path.exists():
        _remove_batch_placeholder(output_path)

    elapsed_time = time.time() - start_time
    total_count = len(batch_results)
    successful_count = sum(1 for r in batch_results if r.success)

    fire_event(
        BatchCompleteEvent(
            batch_id=batch_id,
            action_name=file_name or "default",
            total=total_count,
            completed=successful_count,
            failed=total_count - successful_count,
            elapsed_time=elapsed_time,
        )
    )

    manager.update_status(batch_id, BatchStatus.COMPLETED)
    return str(output_file)


def cleanup_recovery(
    service: "BatchProcessingService",
    manager: BatchRegistryManager,
    output_directory: str,
    parent_file_name: str,
) -> None:
    """Remove recovery batch entries from registry after finalization."""
    service._cleanup_recovery_entries(manager, parent_file_name)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _finalize_and_cleanup(
    service: "BatchProcessingService",
    batch_results: list[BatchResult],
    exhausted_recovery: dict[str, RecoveryMetadata] | None,
    context_map: dict[str, Any],
    output_directory: str,
    parent_file_name: str,
    batch_id: str,
    agent_config: dict[str, Any] | None,
    manager: BatchRegistryManager,
    action_name: str | None,
    start_time: float,
) -> str:
    """Delete recovery state, finalize output, then clean up registry entries."""
    RecoveryStateManager.delete(output_directory, parent_file_name)
    output_path = finalize_batch_output(
        service,
        batch_results=batch_results,
        exhausted_recovery=exhausted_recovery,
        context_map=context_map,
        output_directory=output_directory,
        file_name=parent_file_name,
        batch_id=batch_id,
        agent_config=agent_config,
        manager=manager,
        action_name=action_name,
        start_time=start_time,
    )
    cleanup_recovery(service, manager, output_directory, parent_file_name)
    return output_path


def _register_recovery_batch(
    manager: BatchRegistryManager,
    submission: tuple[str, int],
    parent_file_name: str,
    provider: str,
    recovery_type: Literal["retry", "reprompt"],
    attempt: int,
) -> None:
    """Register a new recovery batch entry in the manager."""
    batch_id, record_count = submission
    recovery_file_name = f"{parent_file_name}_{recovery_type}_{attempt}"
    recovery_entry = BatchJobEntry(
        batch_id=batch_id,
        status=BatchStatus.SUBMITTED,
        timestamp=datetime.now(UTC).isoformat(),
        provider=provider,
        record_count=record_count,
        file_name=recovery_file_name,
        parent_file_name=parent_file_name,
        recovery_type=recovery_type,
        recovery_attempt=attempt,
    )
    manager.save_batch_job(recovery_file_name, recovery_entry)


def _remove_batch_placeholder(output_file: Path) -> None:
    """Remove a batch placeholder file from disk after results are in the backend.

    Only removes if the file matches the placeholder shape (batch_job_id + status=submitted).
    """
    try:
        with open(output_file, encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        return  # File already gone
    except json.JSONDecodeError:
        logger.warning("Malformed JSON at %s during placeholder cleanup", output_file)
        return

    if isinstance(data, dict) and "batch_job_id" in data and data.get("status") == "submitted":
        try:
            output_file.unlink()
            logger.debug("Removed batch placeholder: %s", output_file)
        except OSError:
            pass  # Already removed by concurrent worker


def _stamp_batch_records(records: list[dict[str, Any]], action_name: str) -> None:
    """Stamp _state on batch output records that lack lifecycle fields.

    Batch results bypass the online ResultCollector._stamp() path. This ensures
    every record written to target has a valid _state for Phase 5 fail-closed reads.
    """
    from agent_actions.record.state import RecordState

    for record in records:
        if "_state" in record:
            continue
        # Determine state from record content
        content = record.get("content")
        metadata = record.get("metadata", {})
        if metadata.get("retry_exhausted") or metadata.get("reason") == "exhausted":
            state = RecordState.EXHAUSTED
        elif content is None and metadata.get("reason"):
            state = RecordState.FAILED
        else:
            state = RecordState.PROCESSED
        RecordEnvelope.transition(record, state, action_name, "batch_completion")
