"""Batch repair rounds for `expect:` — the same deferred loop reprompt runs.

Online, `ExpectationService.execute` loops around one call. Batch cannot: a
round is a whole batch submission, so the loop is the graduated pool — evaluate
the set, resubmit only what failed, never re-evaluate what passed — and each
round defers exactly like a reprompt round, so a long-running provider batch
does not hold the process open.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agent_actions.processing.types import ExpectationsMetadata, RecoveryMetadata

if TYPE_CHECKING:
    from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
    from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult
    from agent_actions.processing.evaluation.strategies import ExpectationStrategy
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


def build_repair_strategy(
    agent_config: dict[str, Any] | None,
    judge_budget_remaining: int | None = None,
) -> ExpectationStrategy | None:
    """The action's repair strategy, or None when it does not repair.

    Each deferred round rebuilds this, so the judge budget left from the
    previous round is handed back in — otherwise the budget would bound a round
    instead of the run, and `max_iterations` rounds could spend that many times
    the configured cap.
    """
    from agent_actions.expectations.service import create_expectation_service_from_config
    from agent_actions.processing.evaluation.strategies import ExpectationStrategy

    config = agent_config or {}
    service = create_expectation_service_from_config(
        config.get("expect"),
        action_name=config.get("action_name") or config.get("name", "unknown"),
        agent_config=config,
        judge_budget_remaining=judge_budget_remaining,
    )
    if service is None or service.repair == "none":
        return None
    return ExpectationStrategy(service)


def stamp_exhausted(
    results: list[BatchResult],
    strategy: ExpectationStrategy,
    attempts: int,
) -> None:
    """Record which expectations were still failing when the iterations ran out."""
    for result in results:
        verdict = strategy.verdict_for(result.custom_id)
        failed = [outcome.id for outcome in verdict.failed] if verdict else []
        meta = result.recovery_metadata
        if not isinstance(meta, RecoveryMetadata):
            meta = RecoveryMetadata()
        meta.expectations = ExpectationsMetadata(attempts=attempts, failed=failed)
        result.recovery_metadata = meta


def apply_exhaustion_policy(
    exhausted: list[BatchResult],
    strategy: ExpectationStrategy,
    action_name: str,
) -> None:
    """`return_last` keeps the annotated record; `fail` tombstones it; `raise` halts the run."""
    from agent_actions.expectations.service import ExpectationsExhaustedError

    policy = strategy.on_exhausted
    if policy == "return_last" or not exhausted:
        return

    if policy == "raise":
        first = exhausted[0].recovery_metadata
        expectations = first.expectations if first else None
        raise ExpectationsExhaustedError(
            action_name,
            expectations.failed if expectations else [],
            expectations.attempts if expectations else strategy.max_attempts,
        )

    for result in exhausted:
        meta = result.recovery_metadata
        expectations = meta.expectations if meta else None
        failed = ", ".join(expectations.failed) if expectations and expectations.failed else "none"
        attempts = expectations.attempts if expectations else strategy.max_attempts
        result.success = False
        result.error = f"Expectations exhausted after {attempts} iteration(s) (failed: {failed})"


def submit_repair_batch(
    *,
    action_indices: dict[str, int],
    dependency_configs: dict[str, dict],
    storage_backend: StorageBackend | None,
    provider: BaseBatchClient,
    failed_results: list[BatchResult],
    strategy: ExpectationStrategy,
    context_map: dict[str, Any],
    output_directory: str,
    file_name: str,
    agent_config: dict[str, Any] | None,
    attempt: int,
) -> tuple[str, int] | None:
    """Submit a repair batch for records whose expectations failed, without blocking.

    Returns ``(batch_id, record_count)``, or None when there is nothing to send.
    """
    from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
    from agent_actions.llm.batch.services.reprompt_ops import _load_source_data_for_reprompt

    repair_records: list[dict[str, Any]] = []
    feedback_by_id: dict[str, str] = {}
    for failed in failed_results:
        custom_id = failed.custom_id
        if custom_id not in context_map:
            logger.warning("Cannot repair %s: not found in context_map", custom_id)
            continue
        record = context_map[custom_id].copy()
        record.setdefault("target_id", custom_id)
        feedback_by_id[str(custom_id)] = strategy.build_feedback(failed)
        repair_records.append(record)

    if not repair_records:
        logger.debug("No records to repair")
        return None

    batch_name = f"{file_name}_repair_{attempt}"
    preparator = BatchTaskPreparator(
        action_indices=action_indices,
        dependency_configs=dependency_configs,
        storage_backend=storage_backend,
    )
    prepared = preparator.prepare_tasks(
        agent_config=agent_config or {},
        data=repair_records,
        provider=provider,
        output_directory=output_directory,
        batch_name=batch_name,
        source_data=_load_source_data_for_reprompt(storage_backend),
        feedback_by_id=feedback_by_id,
    )

    batch_id, _status = provider.submit_batch(
        tasks=prepared.tasks,
        batch_name=batch_name,
        output_directory=output_directory,
    )
    logger.info(
        "Async repair batch submitted: %s with %d records (iteration %d)",
        batch_id,
        len(prepared.tasks),
        attempt,
    )
    return batch_id, len(prepared.tasks)


def pool_records(pooled: list[dict[str, Any]], added: list[BatchResult]) -> list[dict[str, Any]]:
    """The graduated pool with *added* folded in, keyed by record, latest winning.

    The pool is what finalisation ships, and both the submitting and the
    resuming pass add to it. The original batch also stays COMPLETED at the
    provider, so every resume re-processes it and re-graduates the same records
    — appending would ship each one again for one source, and a later round's
    repaired content has to replace the attempt it superseded.
    """
    from agent_actions.llm.batch.services.retry_serialization import serialize_results
    from agent_actions.llm.providers.batch_base import UNIDENTIFIED_RECORD

    by_id: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for record in [*pooled, *serialize_results(added)]:
        # Identity is the record id — and the sentinel a provider stamps on a
        # result carrying none is not one. Folding those together would drop
        # records rather than duplicate them, the worse of the two failures.
        #
        # The sentinel shares a namespace with user data (a target_id could
        # literally be it), so a record named that is treated as unidentified
        # and appears once per processing pass instead of deduplicating. That
        # is the wrong answer for a case nothing here can distinguish, and it
        # errs towards a visible duplicate rather than a silent loss.
        key = record.get("custom_id")
        if key and key != UNIDENTIFIED_RECORD:
            by_id[str(key)] = record
        else:
            unkeyed.append(record)
    if unkeyed:
        # Correlation is already broken upstream if this happens — the record
        # cannot be matched to its input either. Say so rather than let it look
        # like an ordinary duplicate in the output.
        logger.warning(
            "%d pooled record(s) carry no usable correlation id and cannot be "
            "deduplicated; they will appear once per processing pass",
            len(unkeyed),
        )
    return [*by_id.values(), *unkeyed]


def carry_forward(
    prior: RecoveryState | None,
    *,
    repair_attempt: int,
    repair_max_attempts: int,
    graduated: list[BatchResult],
    submitted_ids: list[str] | None = None,
    judge_budget_remaining: int | None = None,
) -> RecoveryState:
    """The state a repair round persists, keeping what retry and reprompt put there.

    Finalisation rebuilds `exhausted_recovery` from `missing_ids` and
    `record_failure_counts`, so a repair round that replaced the state with a
    fresh one would drop every record's retry-exhaustion metadata purely because
    a repair happened to fire.
    """
    from agent_actions.llm.batch.core.batch_constants import RecoveryPhase
    from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState

    state = RecoveryState(
        phase=RecoveryPhase.REPAIR,
        repair_attempt=repair_attempt,
        repair_max_attempts=repair_max_attempts,
        repair_submitted_ids=list(submitted_ids or []),
        repair_judge_budget_remaining=judge_budget_remaining,
        graduated_results=pool_records(prior.graduated_results if prior else [], graduated),
        evaluation_strategy_name="expectations",
    )
    if prior is None:
        return state

    state.missing_ids = list(prior.missing_ids)
    state.record_failure_counts = dict(prior.record_failure_counts)
    state.retry_attempt = prior.retry_attempt
    state.retry_max_attempts = prior.retry_max_attempts
    state.reprompt_attempt = prior.reprompt_attempt
    state.reprompt_max_attempts = prior.reprompt_max_attempts
    state.reprompt_attempts_per_record = dict(prior.reprompt_attempts_per_record)
    state.validation_name = prior.validation_name
    state.validation_status = dict(prior.validation_status)
    state.on_exhausted = prior.on_exhausted
    state.accumulated_results = list(prior.accumulated_results)
    state.failure_type_counts = dict(prior.failure_type_counts)
    return state


def dropped_from(submitted_ids: list[str], returned: list[BatchResult]) -> set[str]:
    """The ids sent in a repair round that the provider never returned."""
    from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler

    return set(submitted_ids) - BatchResultReconciler.collect_result_custom_ids(returned)
