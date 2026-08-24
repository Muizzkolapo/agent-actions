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
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.batch.services.retry_serialization import (
    deserialize_results,
    serialize_results,
)
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

from agent_actions.llm.batch.services.repair_ops import RepairSubmission, pool_records

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

    effective_action_name = service._resolve_action_name(action_name)
    state = RecoveryStateManager.load(
        service._storage_backend,  # type: ignore[arg-type]
        effective_action_name,  # type: ignore[arg-type]
        parent_file_name,
    )
    if not state:
        # Without state this entry can never be interpreted, and while it exists
        # it supersedes its parent — so leaving it registered wedges the action
        # on the same error every run. Dropping it hands the parent back to the
        # from-scratch path, which is what a missing state means.
        logger.error(
            "No recovery state for parent=%s file_name=%s — dropping the entry so %s "
            "can be processed from scratch",
            parent_file_name,
            file_name,
            parent_file_name,
        )
        manager.remove_batch_job(file_name)
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
        action_name=effective_action_name,
        start_time=time.time(),
    )
    identity = BatchIdentity(
        batch_id=batch_id,
        file_name=parent_file_name,
        entry=entry,
    )

    context_map = service._context_manager.load_batch_context_map(
        service._storage_backend,  # type: ignore[arg-type]
        effective_action_name,  # type: ignore[arg-type]
        parent_file_name,
    )

    # A terminally failed batch has nothing to retrieve; the empty result set
    # is exactly what it delivered, and the handlers below count the spent
    # attempt from it.
    if entry.status in (BatchStatus.FAILED, BatchStatus.CANCELLED):
        logger.info(
            "Recovery batch %s for parent=%s is %s at the provider — "
            "continuing recovery with no results",
            batch_id,
            parent_file_name,
            entry.status,
        )
        recovery_results: list[BatchResult] = []
    else:
        recovery_results = retrieve_and_reconcile(
            provider,
            batch_id,
            output_directory,
            context_map=context_map,
            record_count=entry.record_count,
            file_name=file_name,
        )

    accumulated = deserialize_results(state.accumulated_results)

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
    elif entry.recovery_type == RecoveryType.REPAIR:
        return handle_repair_recovery(
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
            state.accumulated_results = serialize_results(merged)
            RecoveryStateManager.save(
                context.service._storage_backend,
                context.service._resolve_action_name(context.action_name),
                identity.file_name,
                state,
            )
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

    if not check_and_submit_repair(
        context, identity, batch_results=merged, context_map=context_map, recovery_state=state
    ):
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
        # Merge prior carried-forward results with current cycle before finalizing.
        final_results = deserialize_results(state.graduated_results)
        final_results.extend(deserialize_results(state.unrepromptable_results))
        final_results.extend(recovery_results)
        # Repair still owes these records a verdict: under a repair policy the
        # result assembler does not write one, so a finalize that skips this
        # check ships them with no `expect` block at all.
        if not check_and_submit_repair(
            context,
            identity,
            batch_results=final_results,
            context_map=context_map,
            recovery_state=None,
        ):
            return None
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
    state.graduated_results = pool_records(state.graduated_results, graduated)
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
            reprompt_batch_id, submitted_ids = submission
            submitted = {str(custom_id) for custom_id in submitted_ids}
            unsubmitted = [fr for fr in still_failing if str(fr.custom_id) not in submitted]
            if unsubmitted:
                logger.warning(
                    "Reprompt batch for %s admitted %d of %d records; carrying %s to finalization",
                    identity.file_name,
                    len(submitted),
                    len(submitted) + len(unsubmitted),
                    sorted(str(fr.custom_id) for fr in unsubmitted),
                )
                state.unrepromptable_results = list(state.unrepromptable_results) + (
                    serialize_results(
                        _stamp_withheld(
                            unsubmitted,
                            validation_name,
                            state.reprompt_attempts_per_record,
                            state.failure_type_counts,
                        )
                    )
                )

            register_recovery_batch(
                context.manager,
                (reprompt_batch_id, len(submitted)),
                identity.file_name,
                identity.entry.provider,
                RecoveryType.REPROMPT,
                next_attempt,
            )
            fire_event(
                RepromptRetryEvent(
                    action_name=identity.file_name,
                    attempt=next_attempt,
                    max_attempts=state.reprompt_max_attempts,
                    error=f"{len(submitted)} records failed validation",
                    failed_count=len(submitted),
                )
            )
            for fr in still_failing:
                if str(fr.custom_id) not in submitted:
                    continue
                state.reprompt_attempts_per_record[fr.custom_id] = (
                    state.reprompt_attempts_per_record.get(fr.custom_id, 0) + 1
                )
            state.reprompt_attempt = next_attempt
            RecoveryStateManager.save(
                context.service._storage_backend,
                context.service._resolve_action_name(context.action_name),
                identity.file_name,
                state,
            )
            return None

    # Exhausted or all graduated — finalize.
    if still_failing:
        failed_ids = {r.custom_id for r in still_failing}
        # Parked, not thrown: the file has not been written yet, and halting
        # here would discard every record the reprompt rounds graduated.
        park_halt(
            context,
            context.service._retry_service.apply_exhausted_reprompt_metadata(
                results=still_failing,
                failed_ids=failed_ids,
                validation_name=validation_name,
                attempt=state.reprompt_attempt,
                on_exhausted=state.on_exhausted,
                per_record_attempts=state.reprompt_attempts_per_record or None,
                failure_type_counts=state.failure_type_counts or None,
            ),
        )

    final_results = deserialize_results(state.graduated_results)
    final_results.extend(deserialize_results(state.unrepromptable_results))
    if still_failing:
        final_results.extend(still_failing)

    if state.graduated_results:
        fire_event(
            RepromptRecoveredEvent(
                action_name=identity.file_name,
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

    if not check_and_submit_repair(
        context, identity, batch_results=final_results, context_map=context_map, recovery_state=None
    ):
        return None

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

    # No content is a provider failure, not a content-quality issue — a reprompt
    # has nothing to repair. The withheld records must still be carried to
    # finalization, or they surface there as records the batch never returned.
    repromptable = [r for r in still_failing if r.content is not None]
    unrepromptable = [r for r in still_failing if r.content is None]

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
        park_halt(
            context,
            context.service._retry_service.apply_exhausted_reprompt_metadata(
                results=still_failing,
                failed_ids=failed_ids,
                validation_name=validation_name,
                attempt=current_attempt,
                on_exhausted=on_exhausted,
                per_record_attempts=per_record_attempts,
                failure_type_counts=ftc or None,
            ),
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

    reprompt_batch_id, submitted_ids = submission
    # Preparation can admit fewer records than were handed to it. Whatever it left
    # behind is not in flight, so it belongs with the withheld pool rather than
    # being booked as an attempt nobody made.
    submitted = {str(custom_id) for custom_id in submitted_ids}
    unsubmitted = [fr for fr in repromptable if str(fr.custom_id) not in submitted]
    repromptable = [fr for fr in repromptable if str(fr.custom_id) in submitted]
    unrepromptable = unrepromptable + _stamp_withheld(
        unsubmitted,
        strategy.name,
        dict(recovery_state.reprompt_attempts_per_record) if recovery_state else {},
        ftc,
    )
    if unsubmitted:
        logger.warning(
            "Reprompt batch for %s admitted %d of %d records; carrying %s to finalization",
            identity.file_name,
            len(submitted),
            len(submitted) + len(unsubmitted),
            sorted(str(fr.custom_id) for fr in unsubmitted),
        )

    register_recovery_batch(
        context.manager,
        (reprompt_batch_id, len(submitted)),
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
        graduated_results=pool_records(
            list(recovery_state.graduated_results) if recovery_state else [], graduated
        ),
        unrepromptable_results=pool_records(
            list(recovery_state.unrepromptable_results) if recovery_state else [], unrepromptable
        ),
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

    RecoveryStateManager.save(
        context.service._storage_backend,
        context.service._resolve_action_name(context.action_name),
        identity.file_name,
        state,  # type: ignore[arg-type]
    )
    fire_event(
        RepromptRetryEvent(
            action_name=identity.file_name,
            attempt=next_attempt,
            max_attempts=max_attempts,
            error=f"{len(repromptable)} records failed validation",
            failed_count=len(repromptable),
        )
    )
    logger.info(
        "Async reprompt submitted for %s: %d failed records, batch %s",
        identity.file_name,
        len(repromptable),
        reprompt_batch_id,
    )
    return False


# ---------------------------------------------------------------------------
# Finalization + cleanup
# ---------------------------------------------------------------------------


def park_halt(context: RecoveryContext, pending: Exception | None) -> None:
    """Keep the first halt decided for this file, and say so when a second is dropped.

    Only one error can be raised, and the run stops either way — but an operator
    reading the message would otherwise never learn the other policy had also
    given up.
    """
    if pending is None:
        return
    if context.pending_exhaustion is None:
        context.pending_exhaustion = pending
        return
    logger.warning(
        "A second exhaustion policy also stopped this file; raising the first. Also: %s: %s",
        type(pending).__name__,
        pending,
    )


def finalize_batch_output(
    context: RecoveryContext,
    identity: BatchIdentity,
    batch_results: list[BatchResult],
    context_map: dict[str, Any],
    exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
) -> str:
    """Finalize batch processing: convert, write output, fire events."""
    service = context.service
    processed_data, _stats, converted_halt = service._convert_batch_results_to_workflow_format(
        batch_results,
        context_map=context_map,
        output_directory=context.output_directory,
        agent_config=context.agent_config,
        exhausted_recovery=exhausted_recovery,
    )

    # The conversion hands back a retry-exhaustion halt rather than throwing it,
    # for the same reason the expectations policy does. An expectations halt was
    # decided first, so it keeps precedence.
    park_halt(context, converted_halt)

    effective_action_name = service._resolve_action_name(context.action_name)

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
    successful_count = sum(1 for r in batch_results if BatchResultReconciler.is_answered(r))

    fire_event(
        BatchCompleteEvent(
            batch_id=identity.batch_id,
            action_name=effective_action_name,
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


# A repair round in one of these states will never return records, so it no
# longer owns them and the loop must be free to move on.
_ROUND_ENDED_WITHOUT_RESULTS = frozenset({BatchStatus.FAILED, BatchStatus.CANCELLED})


def _repair_round_in_flight(context: RecoveryContext, identity: BatchIdentity) -> bool:
    """Whether a repair round for this file still owns its records.

    The provider is asked, not the registry. A recovery entry is written
    SUBMITTED and only marked COMPLETED inside `finalize_batch_output`, so its
    status reads as running for the whole life of the file — a round the
    provider had failed would defer every later pass and the output would never
    be written at all.

    A completed round still owns them: its results have not been folded in yet,
    and starting another would buy a second generation of each record. Only a
    round that ended without results releases them.

    A status read that fails is left to propagate. The per-file handler logs it
    and moves to the next file, which beats guessing: "nothing running" pays
    twice, "something running" never finalises.
    """
    jobs = context.manager.get_all_jobs() or {}
    rounds = [
        entry
        for entry in jobs.values()
        if entry.parent_file_name == identity.file_name
        and entry.recovery_type == RecoveryType.REPAIR
        and entry.batch_id
    ]
    for entry in rounds:
        if context.provider.check_status(entry.batch_id) in _ROUND_ENDED_WITHOUT_RESULTS:
            logger.warning(
                "[%s] Repair round %s ended at the provider without results (%s); "
                "its records are back in play",
                identity.file_name,
                entry.recovery_attempt,
                entry.batch_id,
            )
            continue
        return True
    return False


def check_and_submit_repair(
    context: RecoveryContext,
    identity: BatchIdentity,
    batch_results: list[BatchResult],
    context_map: dict[str, Any],
    recovery_state: RecoveryState | None = None,
) -> bool:
    """Evaluate `expect:` and, under a repair policy, submit the next round.

    Returns True when processing should continue — the suite passed, the action
    does not repair, or the iterations are spent. False when a repair batch was
    submitted and the caller should defer.

    On True, *batch_results* holds what the caller should write: a resume of the
    original batch arrives with the results it produced before any repair round,
    so anything the loop has since rewritten is folded in over them.
    """
    from agent_actions.llm.batch.services.repair_ops import (
        apply_exhaustion_policy,
        build_repair_strategy,
        carry_forward,
        pool_records,
        stamp_exhausted,
        submit_repair_batch,
    )
    from agent_actions.llm.batch.services.retry_serialization import serialize_results
    from agent_actions.processing.evaluation import EvaluationLoop

    # Load before building the strategy: the counter and the judge budget both
    # live in persisted state. An entry point that receives None and reads the
    # counter as attempt 0 can never stop iterating, and one that rebuilds the
    # service without the balance spends the budget again every round.
    if recovery_state is None:
        # Every caller that has a live state passes it; the ones that pass None
        # are the re-entry paths, and the persisted bookkeeping is the only
        # record of where the loop got to. A phase guard cannot separate stale
        # from live here — a run that crashed mid-repair leaves a REPAIR state
        # too — so the budget's staleness is a known limitation, not something
        # to approximate by discarding state the reprompt handoff needs.
        recovery_state = RecoveryStateManager.load(
            context.service._storage_backend,
            context.service._resolve_action_name(context.action_name),
            identity.file_name,
        )

    strategy = build_repair_strategy(
        context.agent_config,
        recovery_state.repair_judge_budget_remaining if recovery_state else None,
    )
    if strategy is None:
        return True

    # The original batch's entry is never retired, so every resume arrives here
    # with the same records. A round already running owns them: submitting
    # another buys a second generation for each, and only one of the two can
    # finalise — the loser is orphaned when the winner deletes the state.
    if _repair_round_in_flight(context, identity):
        logger.info("[%s] Repair round already in flight; deferring to it", identity.file_name)
        return False

    # The original batch's registry entry is never retired, so a resume
    # re-enters here holding the pre-repair results. Whatever the loop has
    # already rewritten supersedes them, or finalising this pass would ship the
    # stale content and throw the pool away.
    if recovery_state and recovery_state.graduated_results:
        batch_results[:] = deserialize_results(
            pool_records(
                serialize_results(batch_results),
                deserialize_results(recovery_state.graduated_results),
            )
        )

    loop = EvaluationLoop(strategy)
    graduated, still_failing, _failure_types = loop.split(batch_results)
    loop.tag_graduated(graduated)
    strategy.write_verdicts(graduated)

    # A result with no content failed at the provider, not at its expectations,
    # so there is nothing to regenerate from. It still has to reach the output
    # carrying its own error — dropping it here would turn a reported API
    # failure into a silent "never returned" passthrough.
    repairable = [r for r in still_failing if r.content is not None]
    unrepairable = [r for r in still_failing if r.content is None]

    # max_iterations counts total generations, and the first one already
    # happened — so the rounds available here are one fewer.
    max_rounds = max(strategy.max_attempts - 1, 0)
    current_attempt = recovery_state.repair_attempt if recovery_state else 0

    def _give_up(exhausted: list[BatchResult]) -> bool:
        """Stop the loop for *exhausted*, applying the action's on_exhausted.

        Every exit from here is the loop ending for those records, so they all
        settle the policy the same way — otherwise whether a run halts depends
        on which exit the pass happened to take.
        """
        strategy.write_verdicts(exhausted)
        stamp_exhausted(exhausted, strategy, current_attempt + 1)
        park_halt(
            context,
            apply_exhaustion_policy(
                exhausted, strategy, context.service._resolve_action_name(context.action_name)
            ),
        )
        return True

    if not repairable:
        return _give_up(still_failing)

    if current_attempt >= max_rounds:
        return _give_up(still_failing)

    next_attempt = current_attempt + 1
    submission = submit_repair_batch(
        action_indices=context.service._action_indices,
        dependency_configs=context.service._dependency_configs,
        storage_backend=context.service._storage_backend,
        provider=context.provider,
        failed_results=repairable,
        strategy=strategy,
        context_map=context_map,
        output_directory=context.output_directory,
        file_name=identity.file_name,
        agent_config=context.agent_config,
        attempt=next_attempt,
    )
    if not submission:
        return _give_up(still_failing)

    register_recovery_batch(
        context.manager,
        submission,
        identity.file_name,
        identity.entry.provider,
        RecoveryType.REPAIR,
        next_attempt,
    )

    state = carry_forward(
        recovery_state,
        repair_attempt=next_attempt,
        repair_max_attempts=max_rounds,
        graduated=graduated + unrepairable,
        submitted_ids=list(submission.sent_ids),
        judge_budget_remaining=strategy.judge_budget_remaining,
    )
    RecoveryStateManager.save(
        context.service._storage_backend,
        context.service._resolve_action_name(context.action_name),
        identity.file_name,
        state,  # type: ignore[arg-type]
    )
    logger.info(
        "[%s] Repair round %d/%d submitted for %d record(s); deferring",
        identity.file_name,
        next_attempt,
        max_rounds,
        len(repairable),
    )
    return False


def handle_repair_recovery(
    context: RecoveryContext,
    identity: BatchIdentity,
    state: RecoveryState,
    recovery_results: list[BatchResult],
    accumulated: list[BatchResult],
    context_map: dict[str, Any],
) -> str | None:
    """Continue the repair loop when a repair batch comes back."""
    from agent_actions.llm.batch.services.repair_ops import (
        apply_exhaustion_policy,
        build_repair_strategy,
        dropped_from,
        pool_records,
        stamp_exhausted,
        submit_repair_batch,
    )
    from agent_actions.processing.evaluation import EvaluationLoop

    strategy = build_repair_strategy(context.agent_config, state.repair_judge_budget_remaining)

    if strategy is None:
        return _finalize_and_cleanup(
            context,
            identity,
            batch_results=deserialize_results(
                pool_records(state.graduated_results, recovery_results)
            ),
            context_map=context_map,
        )

    loop = EvaluationLoop(strategy)
    graduated, still_failing, _failure_types = loop.split(recovery_results)
    loop.tag_graduated(graduated)
    strategy.write_verdicts(graduated)
    state.graduated_results = pool_records(state.graduated_results, graduated)
    state.evaluation_strategy_name = strategy.name

    # A record submitted for repair that the provider never returned is in
    # neither bucket. It still has to reach the output, carrying the verdict it
    # had when it was sent.
    dropped_ids = dropped_from(state.repair_submitted_ids, recovery_results)
    if dropped_ids:
        logger.warning(
            "[%s] Repair round %d: provider dropped %d record(s): %s",
            identity.file_name,
            state.repair_attempt,
            len(dropped_ids),
            sorted(dropped_ids),
        )
        # The record was sent for repair, so it is in none of the pools this
        # pass has: it must be reconstructed as a failure rather than left to
        # become a silent "never returned" passthrough.
        dropped = [
            BatchResult(
                custom_id=cid,
                content=None,
                success=False,
                error=f"Repair round {state.repair_attempt} did not return this record",
            )
            for cid in sorted(dropped_ids)
        ]
        stamp_exhausted(dropped, strategy, state.repair_attempt)
        still_failing.extend(dropped)

    repairable = [r for r in still_failing if r.content is not None]
    # Anything not going back to the model — a provider failure, or a record the
    # last round never returned — has to enter the persisted pool now. Only
    # what is resubmitted comes back on the next pass; the rest would be in no
    # pool at all and would vanish from the output.
    carried = [r for r in still_failing if r.content is None]
    if repairable and state.repair_attempt < state.repair_max_attempts:
        next_attempt = state.repair_attempt + 1
        submission = submit_repair_batch(
            action_indices=context.service._action_indices,
            dependency_configs=context.service._dependency_configs,
            storage_backend=context.service._storage_backend,
            provider=context.provider,
            failed_results=repairable,
            strategy=strategy,
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
                RecoveryType.REPAIR,
                next_attempt,
            )
            state.repair_attempt = next_attempt
            state.repair_submitted_ids = list(submission.sent_ids)
            state.repair_judge_budget_remaining = strategy.judge_budget_remaining
            state.graduated_results = pool_records(
                state.graduated_results, carried, in_flight=state.repair_submitted_ids
            )
            RecoveryStateManager.save(
                context.service._storage_backend,
                context.service._resolve_action_name(context.action_name),
                identity.file_name,
                state,  # type: ignore[arg-type]
            )
            return None

    pending = None
    if still_failing:
        strategy.write_verdicts(still_failing)
        stamp_exhausted(still_failing, strategy, state.repair_attempt + 1)
        pending = apply_exhaustion_policy(
            still_failing, strategy, context.service._resolve_action_name(context.action_name)
        )

    # Through the pool rather than concatenated: the returning copy of a record
    # supersedes whatever the pool still holds for it, so one id is one row.
    final_results = deserialize_results(pool_records(state.graduated_results, still_failing))

    # Rebuilt from the retry bookkeeping the repair round carried forward, so a
    # record's retry exhaustion is not lost just because a repair also happened.
    exhausted_recovery = None
    if state.missing_ids:
        exhausted_recovery = context.service._retry_service.build_exhausted_recovery(
            set(state.missing_ids), state.record_failure_counts
        )

    # Parked last: everything above can throw, and the outer loop answers a
    # non-RuntimeError by logging and moving to the next file. Through park_halt
    # so a policy that decided nothing cannot write None over one that did.
    park_halt(context, pending)
    return _finalize_and_cleanup(
        context,
        identity,
        batch_results=final_results,
        context_map=context_map,
        exhausted_recovery=exhausted_recovery,
    )


def raise_pending_exhaustion(context: RecoveryContext) -> None:
    """Halt the run for `on_exhausted: raise`, now that the output is on disk.

    Called from the finalisers, not from the policy itself: batch writes its
    file once at the end, so raising earlier takes down every record the round
    had already graduated. Callers park on the statement before the finaliser,
    because anything that throws in between reaches the outer loop, which logs
    a non-RuntimeError and moves on — forgetting the halt.
    """
    pending = context.pending_exhaustion
    if pending is None:
        return
    context.pending_exhaustion = None
    raise pending


def _finalize_and_cleanup(
    context: RecoveryContext,
    identity: BatchIdentity,
    batch_results: list[BatchResult],
    context_map: dict[str, Any],
    exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
) -> str:
    """Delete recovery state, finalize output, then clean up registry entries."""
    RecoveryStateManager.delete(
        context.service._storage_backend,
        context.service._resolve_action_name(context.action_name),
        identity.file_name,
    )
    output_path = finalize_batch_output(
        context,
        identity,
        batch_results=batch_results,
        context_map=context_map,
        exhausted_recovery=exhausted_recovery,
    )
    cleanup_recovery(context, identity)
    raise_pending_exhaustion(context)
    return output_path


def _stamp_withheld(
    records: list[BatchResult],
    validation_name: str,
    attempts_made: dict[str, int],
    failure_type_counts: dict[str, dict[str, int]],
) -> list[BatchResult]:
    """Mark records that never reached the reprompt batch as still failing.

    They were repromptable, so they carry content — without a failure stamp they
    collect as successes and the operator never sees that validation rejected them.
    The count comes from the per-record ledger, which does not book an attempt for
    a record that was not sent: stamping the round number instead would make one
    that never left look like one that was tried and failed.
    """
    from agent_actions.processing.types import RepromptMetadata

    for record in records:
        if record.recovery_metadata is None:
            record.recovery_metadata = RecoveryMetadata()
        if record.recovery_metadata.reprompt is None:
            counts = failure_type_counts.get(str(record.custom_id), {})
            record.recovery_metadata.reprompt = RepromptMetadata(
                attempts=attempts_made.get(str(record.custom_id), 0),
                passed=False,
                validation=validation_name,
                parse_error_count=counts.get("parse_error", 0),
                schema_fail_count=counts.get("schema_fail", 0),
                udf_fail_count=counts.get("udf_fail", 0),
            )
    return records


def register_recovery_batch(
    manager: BatchRegistryManager,
    submission: "tuple[str, int] | RepairSubmission",
    parent_file_name: str,
    provider: str,
    recovery_type: RecoveryType,
    attempt: int,
) -> None:
    """Register a new recovery batch entry, replacing the attempt it supersedes.

    One recovery state per parent means one live recovery batch per parent. Left
    in place, a spent attempt is still COMPLETED, so the next run re-processes it
    and finalizes on stale results — deleting the live attempt's entry, and with
    it whatever that attempt recovered.
    """
    if isinstance(submission, tuple):
        batch_id, record_count = submission
    else:
        batch_id, record_count = submission.batch_id, submission.record_count
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

    # After the save, never before: a crash in between must leave the successor
    # registered, not leave the parent with no recovery at all.
    for name, entry in manager.get_all_jobs().items():
        if entry.parent_file_name == parent_file_name and name != recovery_file_name:
            logger.info("Superseding recovery entry %s with %s", name, recovery_file_name)
            manager.remove_batch_job(name)


def _remove_batch_placeholder(output_file: Path) -> None:
    """Remove a batch placeholder file from disk after results are in the backend.

    Since placeholders are no longer written at submission time, this is a
    no-op for new runs. Kept as a guard for pre-migration data that may
    still have placeholder files on disk.
    """
    if not output_file.exists():
        return

    try:
        with open(output_file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    if (
        isinstance(data, dict)
        and "batch_job_id" in data
        and data.get("status") == BatchStatus.SUBMITTED
    ):
        try:
            output_file.unlink()
            logger.debug("Removed legacy batch placeholder: %s", output_file)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Failed to remove batch placeholder %s: %s", output_file, e)
