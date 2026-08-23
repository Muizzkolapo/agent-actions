"""Batch repair rounds for `expect:` — the same loop reprompt runs, different strategy.

Under a repair policy an action regenerates records whose expectations failed.
Online, `ExpectationService.execute` loops around one call; in batch the loop is
the graduated pool: evaluate the whole set, resubmit only what failed, and never
re-evaluate what already passed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agent_actions.processing.types import ExpectationsMetadata, RecoveryMetadata

if TYPE_CHECKING:
    from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult
    from agent_actions.processing.evaluation.strategies import ExpectationStrategy
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


def build_repair_strategy(agent_config: dict[str, Any] | None) -> ExpectationStrategy | None:
    """The action's repair strategy, or None when it does not repair."""
    from agent_actions.expectations.service import create_expectation_service_from_config
    from agent_actions.processing.evaluation.strategies import ExpectationStrategy

    config = agent_config or {}
    service = create_expectation_service_from_config(
        config.get("expect"),
        action_name=config.get("action_name") or config.get("name", "unknown"),
        agent_config=config,
    )
    if service is None or service.repair == "none":
        return None
    return ExpectationStrategy(service)


def _stamp_exhausted(
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


def repair_expectations(
    *,
    action_indices: dict[str, int],
    dependency_configs: dict[str, dict],
    storage_backend: StorageBackend | None,
    results: list[BatchResult],
    provider: BaseBatchClient,
    context_map: dict[str, Any],
    output_directory: str,
    file_name: str,
    agent_config: dict[str, Any] | None,
) -> list[BatchResult]:
    """Regenerate records whose expectations failed, up to `max_iterations` total.

    Returns every record — repaired, still failing, or never failing — with its
    verdict written onto the record and, on exhaustion, the policy the config
    asked for applied.
    """
    from agent_actions.llm.batch.services.reprompt_ops import _load_source_data_for_reprompt
    from agent_actions.llm.batch.services.resubmission import resubmit_round
    from agent_actions.processing.evaluation import EvaluationLoop

    strategy = build_repair_strategy(agent_config)
    if strategy is None:
        return results

    stamp = _stamp_exhausted
    source_data = _load_source_data_for_reprompt(storage_backend)
    loop = EvaluationLoop(strategy)
    all_graduated: list[BatchResult] = []
    active_results = results
    max_iterations = strategy.max_attempts

    for iteration in range(1, max_iterations + 1):
        graduated, still_failing, _failure_types = loop.split(active_results)
        all_graduated.extend(graduated)

        if not still_failing:
            break

        logger.info(
            "[%s] Expectations failed (iteration %d/%d): %d record(s)",
            file_name,
            iteration,
            max_iterations,
            len(still_failing),
        )

        if iteration == max_iterations:
            stamp(still_failing, strategy, iteration)
            all_graduated.extend(still_failing)
            break

        repair_records: list[dict[str, Any]] = []
        feedback_by_id: dict[str, str] = {}
        for failed in still_failing:
            if failed.custom_id not in context_map:
                logger.warning("Cannot repair %s: not found in context_map", failed.custom_id)
                continue
            record = context_map[failed.custom_id].copy()
            record.setdefault("target_id", failed.custom_id)
            feedback_by_id[str(failed.custom_id)] = strategy.build_feedback(failed)
            repair_records.append(record)

        if not repair_records:
            stamp(still_failing, strategy, iteration)
            all_graduated.extend(still_failing)
            break

        outcome = resubmit_round(
            records=repair_records,
            feedback_by_id=feedback_by_id,
            batch_name=f"{file_name}_repair_{iteration}",
            submitted_ids={r.custom_id for r in still_failing},
            provider=provider,
            output_directory=output_directory,
            agent_config=agent_config or {},
            action_indices=action_indices,
            dependency_configs=dependency_configs,
            storage_backend=storage_backend,
            source_data=source_data,
            attempt=iteration,
        )

        if outcome.results is None:
            stamp(still_failing, strategy, iteration)
            all_graduated.extend(still_failing)
            break

        if outcome.dropped_ids:
            dropped = [r for r in still_failing if r.custom_id in outcome.dropped_ids]
            stamp(dropped, strategy, iteration)
            all_graduated.extend(dropped)

        # Carry the inner recovery layers forward: a record repaired on this
        # round still has whatever retry and reprompt did to reach the first one.
        previous = {r.custom_id: r for r in still_failing}
        for repaired in outcome.results:
            earlier = previous.get(repaired.custom_id)
            if earlier is None or earlier.recovery_metadata is None:
                continue
            if repaired.recovery_metadata is None:
                repaired.recovery_metadata = RecoveryMetadata()
            repaired.recovery_metadata.retry = earlier.recovery_metadata.retry
            repaired.recovery_metadata.reprompt = earlier.recovery_metadata.reprompt

        active_results = outcome.results

    strategy.write_verdicts(all_graduated)

    exhausted = [r for r in all_graduated if _is_exhausted(r)]
    if exhausted:
        _apply_exhaustion_policy(exhausted, strategy, file_name)

    return all_graduated


def _is_exhausted(result: BatchResult) -> bool:
    meta = result.recovery_metadata
    return bool(meta and meta.expectations)


def _apply_exhaustion_policy(
    exhausted: list[BatchResult],
    strategy: ExpectationStrategy,
    action_name: str,
) -> None:
    """`return_last` keeps the annotated record; `fail` tombstones it; `raise` halts the run."""
    from agent_actions.expectations.service import ExpectationsExhaustedError

    policy = strategy.on_exhausted
    if policy == "return_last":
        return

    if policy == "raise":
        first = exhausted[0]
        meta = first.recovery_metadata
        expectations = meta.expectations if meta else None
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
