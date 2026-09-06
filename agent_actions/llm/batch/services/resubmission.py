"""One resubmission round: prepare, submit, wait, retrieve, reconcile.

Shared by every batch loop that sends failing records back to the model, so no
two can drift on what "resubmit this set" means.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.batch.services.retry_polling import wait_for_batch_completion

if TYPE_CHECKING:
    from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


@dataclass
class RoundOutcome:
    """What came back from one resubmission.

    ``results`` is None when the round could not complete at all; the caller
    decides how to stamp the records it had already committed to sending.
    """

    results: list[BatchResult] | None = None
    dropped_ids: set[str] = field(default_factory=set)
    incomplete_status: BatchStatus | None = None


def resubmit_round(
    *,
    records: list[dict[str, Any]],
    feedback_by_id: dict[str, str],
    batch_name: str,
    submitted_ids: set[str],
    provider: BaseBatchClient,
    output_directory: str,
    agent_config: dict[str, Any],
    action_indices: dict[str, int],
    dependency_configs: dict[str, dict],
    storage_backend: StorageBackend | None,
    source_data: Any,
    attempt: int,
) -> RoundOutcome:
    """Send *records* back to the model with their feedback and collect the replies.

    Feedback is attached before the provider converts the rows to its wire
    format — after that conversion there is no ``target_id`` left to key on.
    """
    from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator

    preparator = BatchTaskPreparator(
        action_indices=action_indices,
        dependency_configs=dependency_configs,
        storage_backend=storage_backend,
    )
    prepared = preparator.prepare_tasks(
        agent_config=agent_config,
        data=records,
        provider=provider,
        output_directory=output_directory,
        batch_name=batch_name,
        source_data=source_data,
        attempt=attempt,
        feedback_by_id=feedback_by_id,
    )

    batch_id, _status = provider.submit_batch(
        tasks=prepared.tasks,
        batch_name=batch_name,
        output_directory=output_directory,
    )
    logger.info("Submitted batch %s with %d records", batch_id, len(prepared.tasks))

    final_status = wait_for_batch_completion(provider, batch_id, total_items=len(prepared.tasks))
    if final_status != BatchStatus.COMPLETED:
        logger.error("Batch %s did not complete: %s", batch_id, final_status)
        return RoundOutcome(results=None, incomplete_status=final_status)

    results = provider.retrieve_results(batch_id, output_directory)
    received_ids = BatchResultReconciler.collect_result_custom_ids(results)
    dropped_ids = submitted_ids - received_ids
    if dropped_ids:
        logger.warning(
            "Batch %s: provider dropped %d of %d records: %s",
            batch_id,
            len(dropped_ids),
            len(submitted_ids),
            sorted(dropped_ids),
        )
    return RoundOutcome(results=results, dropped_ids=dropped_ids)
