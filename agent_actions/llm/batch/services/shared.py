"""Shared result retrieval logic for batch services."""

import logging
from typing import TYPE_CHECKING, Any, cast

from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult

if TYPE_CHECKING:
    from agent_actions.config.types import ActionConfigDict
    from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


def retrieve_and_reconcile(
    provider: BaseBatchClient,
    batch_id: str,
    output_directory: str | None,
    *,
    context_map: dict[str, Any] | None = None,
    record_count: int | None = None,
    file_name: str | None = None,
    agent_config: dict[str, Any] | None = None,
) -> list[BatchResult]:
    """Retrieve batch results from provider and log reconciliation.

    With *agent_config*, an ``add_dispatch`` action's answers come back holding the
    schema each record's dispatch chose, as an online call returns them: every later
    step (a rule, a repair prompt, the stored record) reads the answer online reads.
    """
    from agent_actions.llm.batch.processing.batch_result_strategy import (
        dispatch_results,
        with_dispatch_results,
    )
    from agent_actions.llm.batch.processing.reconciler import (
        BatchResultReconciler,
    )

    batch_results = provider.retrieve_results(batch_id, output_directory)
    for result in batch_results:
        if BatchResultReconciler.is_answered(result):
            row = (context_map or {}).get(str(result.custom_id))
            result.content = with_dispatch_results(
                result.content, dispatch_results(agent_config, row)
            )

    # Log reconciliation
    BatchResultReconciler.report_unparseable_lines(batch_results)

    expected = BatchResultReconciler.collect_expected_custom_ids(context_map or {})
    answered = BatchResultReconciler.collect_result_custom_ids(
        [r for r in batch_results if BatchResultReconciler.is_answered(r)]
    )
    BatchResultReconciler.log_batch_reconciliation(
        batch_id=batch_id,
        expected_count=len(expected) or record_count or 0,
        answered_count=len(answered),
        file_name=file_name,
    )

    return batch_results


def recovery_preparator(
    storage_backend: "StorageBackend | None",
    agent_config: dict[str, Any] | None,
    action_indices: dict[str, int],
    dependency_configs: dict[str, dict],
) -> "BatchTaskPreparator":
    """The preparator a retry or repair round rebuilds its prompts with, built as the first submission's was.

    A versioned action's prompt and guard read `version.*`, which only the
    pipeline context carries.
    """
    from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
    from agent_actions.workflow.pipeline import ProcessingPipeline

    _, _, version_context = ProcessingPipeline._build_pipeline_context(
        cast("ActionConfigDict", agent_config or {}), dependency_configs
    )
    return BatchTaskPreparator(
        action_indices=action_indices,
        dependency_configs=dependency_configs,
        storage_backend=storage_backend,
        version_context=version_context,
    )
