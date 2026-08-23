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
