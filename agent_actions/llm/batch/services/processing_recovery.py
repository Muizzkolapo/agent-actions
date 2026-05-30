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
from typing import TYPE_CHECKING, Any

from agent_actions.llm.batch.core.batch_constants import BatchStatus, RecoveryPhase, RecoveryType
from agent_actions.llm.batch.core.batch_models import BatchIdentity, BatchJobEntry, RecoveryContext
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
from agent_actions.processing.evaluation.loop import accumulate_failure_types
from agent_actions.processing.types import RecoveryMetadata

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
    parent_file_name = entry.parent_file_name
    if not parent_file_name:
        logger.error(
            "Recovery entry file_name=%s batch_id=%s has no parent_file_name",
            file_name,
            entry.batch_id,
        )
        return None

    state = RecoveryStateManager.load(output_directory, parent_file_name)
    if not state:
        logger.error(
            "No recovery state found for parent=%s file_name=%s", parent_file_name, file_name
        )
        return None

    agent_config = service._apply_workflow_session_id(agent_config, entry)
    provider = service._client_resolver.get_for_batch_id(
        batch_id, manager, output_directory, agent_config=agent_config
    )

    context = RecoveryContext(
        service=service,
        manager=manager,
        provider=provider,
        agent_config=agent_config or {},
        output_directory=output_directory,
        action_name=action_name,
        start_time=time.time(),
    )
    identity = BatchIdentity(
        batch_id=batch_id,
        file_name=parent_file_name,
        entry=entry,
    )

    context_map = service._context_manager.load_batch_context_map(
        output_directory, parent_file_name
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

    if entry.recovery_type == RecoveryType.RETRY:
        return handle_retry_recovery(
            context,
            identity,
            state=state,
            recovery_results=recovery_results,
            accumulated=accumulated,
            context_map=context_map,
        )
    elif entry.recovery_type == RecoveryType.REPROMPT:
        return handle_reprompt_recovery(
            context,
            identity,
            state=state,
            recovery_results=recovery_results,
            accumulated=accumulated,
            context_map=context_map,
        )

    logger.error("Unknown recovery_type: %s", entry.recovery_type)
    return None


# ---------------------------------------------------------------------------
# Retry recovery
# ---------------------------------------------------------------------------


def handle_retry_recovery(
    context: RecoveryContext,
    identity: BatchIdentity,
    state: RecoveryState,
    recovery_results: list[BatchResult],
    accumulated: list[BatchResult],
    context_map: dict[str, Any],
) -> str | None:
    """Handle retry recovery batch completion."""
    merged, still_missing, updated_counts, _ = context.service._retry_service.process_retry_results(
        results=recovery_results,
        accumulated_results=accumulated,
        context_map=context_map,
        record_failure_counts=state.record_failure_counts,
        missing_ids=set(state.missing_ids),
    )

    if still_missing and state.retry_attempt < state.retry_max_attempts:
        next_attempt = state.retry_attempt + 1
        submission = context.service._retry_service.submit_retry_batch(
            provider=context.provider,
            missing_ids=still_missing,
            context_map=context_map,
            output_directory=context.output_directory,
            file_name=identity.file_name,
            agent_config=context.agent_config,
        )
        if submission:
            register_recovery_batch(
                context.manager,
                submission,
                identity.file_name,
                identity.entry.provider,
                RecoveryType.RETRY,
                next_attempt,
            )
            state.retry_attempt = next_attempt
            state.missing_ids = list(still_missing)
            state.record_failure_counts = updated_counts
            state.accumulated_results = BatchRetryService.serialize_results(merged)
            RecoveryStateManager.save(context.output_directory, identity.file_name, state)
            return None

    exhausted_recovery = None
    if still_missing:
        exhausted_recovery = context.service._retry_service.build_exhausted_recovery(
            still_missing, updated_counts
        )

    should_continue = check_and_submit_reprompt(
        context,
        identity,
        batch_results=merged,
        context_map=context_map,
        recovery_state=state,
        exhausted_recovery=exhausted_recovery,
    )
    if not should_continue:
        return None

    return _finalize_and_cleanup(
        context,
        identity,
        batch_results=merged,
        context_map=context_map,
        exhausted_recovery=exhausted_recovery,
    )


# ---------------------------------------------------------------------------
# Reprompt recovery
# ---------------------------------------------------------------------------


def handle_reprompt_recovery(
    context: RecoveryContext,
    identity: BatchIdentity,
    state: RecoveryState,
    recovery_results: list[BatchResult],
    accumulated: list[BatchResult],
    context_map: dict[str, Any],
) -> str | None:
    """Handle reprompt recovery batch completion.

    Uses the graduated pool pattern: only recovery_results are evaluated
    (never the full accumulated set). Graduated records are persisted to
    state and never re-evaluated.
    """
    from agent_actions.llm.batch.services.reprompt_ops import build_evaluation_loop

    setup = build_evaluation_loop(
        context.agent_config,
        max_attempts=state.reprompt_max_attempts,
        on_exhausted=state.on_exhausted,
    )
    if setup is None:
        # Merge prior graduated results with current cycle before finalizing.
        final_results = BatchRetryService.deserialize_results(state.graduated_results)
        final_results.extend(recovery_results)
        return _finalize_and_cleanup(
            context,
            identity,
            batch_results=final_results,
            context_map=context_map,
            exhausted_recovery=None,
        )

    loop, strategy = setup
    validation_name = strategy.name
    graduated, still_failing, failure_types = loop.split(recovery_results)
    loop.tag_graduated(graduated)
    state.graduated_results.extend(BatchRetryService.serialize_results(graduated))
    state.evaluation_strategy_name = validation_name

    accumulate_failure_types(state.failure_type_counts, failure_types)

    if still_failing and state.reprompt_attempt < state.reprompt_max_attempts:
        next_attempt = state.reprompt_attempt + 1
        submission = context.service._retry_service.submit_reprompt_batch(
            provider=context.provider,
            failed_results=still_failing,
            context_map=context_map,
            output_directory=context.output_directory,
            file_name=identity.file_name,
            agent_config=context.agent_config,
            attempt=next_attempt,
        )
        if submission:
            register_recovery_batch(
                context.manager,
                submission,
                identity.file_name,
                identity.entry.provider,
                RecoveryType.REPROMPT,
                next_attempt,
            )
            fire_event(
                RepromptRetryEvent(
                    action_name=identity.file_name or "batch",
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
            RecoveryStateManager.save(context.output_directory, identity.file_name, state)
            return None

    # Exhausted or all graduated — finalize.
    if still_failing:
        failed_ids = {r.custom_id for r in still_failing}
        context.service._retry_service.apply_exhausted_reprompt_metadata(
            results=still_failing,
            failed_ids=failed_ids,
            validation_name=validation_name,
            attempt=state.reprompt_attempt,
            on_exhausted=state.on_exhausted,
            per_record_attempts=state.reprompt_attempts_per_record or None,
            failure_type_counts=state.failure_type_counts or None,
        )

    final_results = BatchRetryService.deserialize_results(state.graduated_results)
    if still_failing:
        final_results.extend(still_failing)

    if state.graduated_results:
        fire_event(
            RepromptRecoveredEvent(
                action_name=identity.file_name or "batch",
                attempt=state.reprompt_attempt,
                max_attempts=state.reprompt_max_attempts,
                validation_name=validation_name,
            )
        )

    # Rebuild exhausted_recovery from retry phase state (frozen at phase transition).
    exhausted_recovery = None
    if state.missing_ids:
        exhausted_recovery = context.service._retry_service.build_exhausted_recovery(
            set(state.missing_ids), state.record_failure_counts
        )

    return _finalize_and_cleanup(
        context,
        identity,
        batch_results=final_results,
        context_map=context_map,
        exhausted_recovery=exhausted_recovery,
    )


# ---------------------------------------------------------------------------
# Reprompt check + submission
# ---------------------------------------------------------------------------


def check_and_submit_reprompt(
    context: RecoveryContext,
    identity: BatchIdentity,
    batch_results: list[BatchResult],
    context_map: dict[str, Any],
    recovery_state: RecoveryState | None = None,
    exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
) -> bool:
    """Check if reprompt is needed and submit async batch if so.

    Returns:
        True if processing should continue (no reprompt needed or exhausted).
        False if a reprompt batch was submitted (caller should return None).
    """
    from agent_actions.llm.batch.services.reprompt_ops import build_evaluation_loop

    setup = build_evaluation_loop(context.agent_config)
    if setup is None:
        return True

    loop, strategy = setup
    validation_name = strategy.name
    max_attempts = strategy.max_attempts
    on_exhausted = strategy.on_exhausted

    graduated, still_failing, failure_types = loop.split(batch_results)
    loop.tag_graduated(graduated)

    # Filter out records with None content (provider failures, not content quality issues)
    repromptable = [r for r in still_failing if r.content is not None]

    if not repromptable:
        return True

    current_attempt = recovery_state.reprompt_attempt if recovery_state else 0

    # Seed from prior-round counts (if resuming from persisted state)
    ftc: dict[str, dict[str, int]] = (
        dict(recovery_state.failure_type_counts) if recovery_state else {}
    )
    accumulate_failure_types(ftc, failure_types)

    if current_attempt >= max_attempts:
        failed_ids = {r.custom_id for r in still_failing}
        per_record_attempts = (
            recovery_state.reprompt_attempts_per_record if recovery_state else None
        )
        context.service._retry_service.apply_exhausted_reprompt_metadata(
            results=still_failing,
            failed_ids=failed_ids,
            validation_name=validation_name,
            attempt=current_attempt,
            on_exhausted=on_exhausted,
            per_record_attempts=per_record_attempts,
            failure_type_counts=ftc or None,
        )
        return True

    next_attempt = current_attempt + 1
    submission = context.service._retry_service.submit_reprompt_batch(
        provider=context.provider,
        failed_results=repromptable,
        context_map=context_map,
        output_directory=context.output_directory,
        file_name=identity.file_name,
        agent_config=context.agent_config,
        attempt=next_attempt,
    )

    if not submission:
        return True

    register_recovery_batch(
        context.manager,
        submission,
        identity.file_name,
        identity.entry.provider,
        RecoveryType.REPROMPT,
        next_attempt,
    )

    state = RecoveryState(
        phase=RecoveryPhase.REPROMPT,
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
        failure_type_counts=ftc,
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

    RecoveryStateManager.save(context.output_directory, identity.file_name, state)
    fire_event(
        RepromptRetryEvent(
            action_name=identity.file_name or "batch",
            attempt=next_attempt,
            max_attempts=max_attempts,
            error=f"{len(still_failing)} records failed validation",
            failed_count=len(still_failing),
        )
    )
    logger.info(
        "Async reprompt submitted for %s: %d failed records, batch %s",
        identity.file_name,
        len(repromptable),
        submission[0],
    )
    return False


# ---------------------------------------------------------------------------
# Finalization + cleanup
# ---------------------------------------------------------------------------


def finalize_batch_output(
    context: RecoveryContext,
    identity: BatchIdentity,
    batch_results: list[BatchResult],
    context_map: dict[str, Any],
    exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
) -> str:
    """Finalize batch processing: convert, write output, fire events."""
    service = context.service
    processed_data, _stats = service._convert_batch_results_to_workflow_format(
        batch_results,
        context_map=context_map,
        output_directory=context.output_directory,
        agent_config=context.agent_config,
        exhausted_recovery=exhausted_recovery,
    )

    effective_action_name = (
        context.action_name if context.action_name is not None else service._action_name
    )

    # SUCCESS/FAILED/EXHAUSTED dispositions and state stamping are handled by the
    # shared collector inside _convert_batch_results_to_workflow_format. FILTERED
    # records are stripped by the reconciler before collection, so they require
    # an explicit write here to match online ResultCollector parity (Phase 7b /
    # U-3.2a). DEFERRED clearing and prompt trace updates also remain batch-specific.
    if service._storage_backend and effective_action_name:
        service._clear_deferred_dispositions(processed_data, effective_action_name)
        service._write_filtered_dispositions(context_map, effective_action_name)
        service._update_prompt_trace_responses(processed_data, effective_action_name)

    output_file = service._determine_output_path(
        context.output_directory, identity.file_name, identity.batch_id
    )
    service._write_batch_output(
        output_file, processed_data, context.output_directory, context.action_name
    )

    # Remove batch placeholder file if storage backend wrote to SQLite instead.
    # The placeholder (written at batch submission) persists on disk when
    # write_target goes to the backend, causing downstream reads to hit it.
    output_path = Path(output_file) if not isinstance(output_file, Path) else output_file
    if service._storage_backend and output_path.exists():
        _remove_batch_placeholder(output_path)

    elapsed_time = time.time() - context.start_time
    total_count = len(batch_results)
    successful_count = sum(1 for r in batch_results if r.success)

    fire_event(
        BatchCompleteEvent(
            batch_id=identity.batch_id,
            action_name=identity.file_name or "default",
            total=total_count,
            completed=successful_count,
            failed=total_count - successful_count,
            elapsed_time=elapsed_time,
        )
    )

    context.manager.update_status(identity.batch_id, BatchStatus.COMPLETED)
    return str(output_file)


def cleanup_recovery(
    context: RecoveryContext,
    identity: BatchIdentity,
) -> None:
    """Remove recovery batch entries from registry after finalization."""
    context.service._cleanup_recovery_entries(context.manager, identity.file_name)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _finalize_and_cleanup(
    context: RecoveryContext,
    identity: BatchIdentity,
    batch_results: list[BatchResult],
    context_map: dict[str, Any],
    exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
) -> str:
    """Delete recovery state, finalize output, then clean up registry entries."""
    RecoveryStateManager.delete(context.output_directory, identity.file_name)
    output_path = finalize_batch_output(
        context,
        identity,
        batch_results=batch_results,
        context_map=context_map,
        exhausted_recovery=exhausted_recovery,
    )
    cleanup_recovery(context, identity)
    return output_path


def register_recovery_batch(
    manager: BatchRegistryManager,
    submission: tuple[str, int],
    parent_file_name: str,
    provider: str,
    recovery_type: RecoveryType,
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

    if (
        isinstance(data, dict)
        and "batch_job_id" in data
        and data.get("status") == BatchStatus.SUBMITTED
    ):
        try:
            output_file.unlink()
            logger.debug("Removed batch placeholder: %s", output_file)
        except FileNotFoundError:
            pass  # Already removed by concurrent worker
        except OSError as e:
            logger.warning("Failed to remove batch placeholder %s: %s", output_file, e)
