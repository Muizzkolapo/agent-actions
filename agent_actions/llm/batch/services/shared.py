"""Shared result retrieval logic for batch services."""

import logging
from typing import TYPE_CHECKING, Any, cast

from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult
from agent_actions.output.response.config_fields import get_default
from agent_actions.output.response.response_builder import ResponseBuilder

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

    A `json_mode: false` action gets each answer as text under its `output_field`
    (*agent_config*), before the expectation loop checks it against the schema.
    """
    from agent_actions.llm.batch.processing.reconciler import (
        BatchResultReconciler,
    )

    batch_results = provider.retrieve_results(batch_id, output_directory)
    keep_text_output(batch_results, agent_config)

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


def keep_text_output(batch_results: list[BatchResult], agent_config: dict[str, Any] | None) -> None:
    """Put each answer of a `json_mode: false` action under its `output_field`, as text.

    The batch clients parse every text answer as JSON, so a plain-text answer that is JSON
    text arrives as an object and other text as a bare string. Online, `call_non_json` wraps
    the text (`ResponseBuilder.wrap_non_json`); this is the batch counterpart. Without it the
    expectation loop checks `{questions: ...}` or `"Q1: PASS"` against a `{raw: ...}` schema
    and fails every repair round.
    """
    if not agent_config:
        return
    if agent_config.get("json_mode", get_default("json_mode")):
        # Only a plain-text action reads the text; do not persist it again between rounds.
        for result in batch_results:
            result.raw_text = None
        return
    for result in batch_results:
        # Only text the model wrote is wrapped. An answer with no text (thinking only) or
        # structured content with no text is left as it is, so the schema check still sees it.
        if result.success and result.raw_text is not None:
            result.content = ResponseBuilder.wrap_non_json(result.raw_text, agent_config)[0]


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
