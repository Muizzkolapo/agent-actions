"""Shared result retrieval logic for batch services."""

import logging
from typing import TYPE_CHECKING, Any, cast

from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult
from agent_actions.llm.providers.usage_tracker import MAIN, TOKEN_FIELDS, record_batch
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
    usage_kind: str = MAIN,
    model: str | None = None,
) -> list[BatchResult]:
    """Retrieve batch results from provider and log reconciliation.

    What the results used is counted here, where every batch of a run is read, as
    *usage_kind* calls of *model* (the action's model when not given).

    Given the *agent_config* of the action the results answer, each reply is read as its
    online call returns it, since a provider parses a line not knowing the action's mode:
    a text-mode reply becomes its text under the output field, a line that holds no
    readable answer is settled as its mode's online call ends it (`settle_unanswered`),
    and an ``add_dispatch`` action's answers hold the schema each record's dispatch chose.
    Every later step (a rule, a repair prompt, the stored record) reads that answer.
    """
    from agent_actions.llm.batch.processing.batch_result_strategy import dispatch_results
    from agent_actions.llm.batch.processing.reconciler import (
        BatchResultReconciler,
    )
    from agent_actions.processing.helpers import with_dispatch_results

    batch_results = provider.retrieve_results(batch_id, output_directory)
    count_batch_usage(
        batch_id,
        batch_results,
        kind=usage_kind,
        model=model or (agent_config or {}).get("model_name"),
    )
    if agent_config is not None:
        json_mode = agent_config.get("json_mode", get_default("json_mode"))
        if not json_mode:
            for result in batch_results:
                if result.text is not None:
                    (result.content,) = ResponseBuilder.wrap_non_json(result.text, agent_config)
                elif result.no_text is not None:
                    result.content = None
                    result.error = str(result.no_text.error) if result.no_text.error else None
                    result.retriable = result.no_text.retried
        settle_unanswered(batch_results, json_mode=json_mode)
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


def wrap_carried_text(results: list[BatchResult], agent_config: dict[str, Any] | None) -> None:
    """Put each carried text answer of a text-mode action under its output field.

    A recovery state that a version before the retrieval wrap wrote holds such an answer
    as a bare string, while this round's answers are wrapped; one output must not mix both.
    """
    if agent_config is None or agent_config.get("json_mode", get_default("json_mode")):
        return
    for result in results:
        if result.success and isinstance(result.content, str):
            (result.content,) = ResponseBuilder.wrap_non_json(result.content, agent_config)


def count_batch_usage(
    batch_id: str, batch_results: list[BatchResult], *, kind: str, model: str | None
) -> None:
    """Count what a batch's results used, each read as its vendor's online call reads its own.

    A line the provider answered is a call, whatever it says of its usage; a request that
    failed before any answer is none.
    """
    usage = dict.fromkeys(TOKEN_FIELDS, 0)
    calls = 0
    for result in batch_results:
        if not result.success and not result.usage:
            continue
        calls += 1
        for field, count in ResponseBuilder.batch_usage(result.usage).counted().items():
            usage[field] += count
    record_batch(batch_id, usage, calls=calls, kind=kind, model=model)


def settle_unanswered(batch_results: list[BatchResult], *, json_mode: bool) -> None:
    """Give each line with no readable answer the content its mode's online call returns.

    A provider's line does not say which mode asked for it. In JSON mode online returns a
    ``_parse_error`` record for an answer that is missing, refused or cut off, which is
    stored failed or regenerated by ``expect:``. In text mode an answer the model left
    empty is the empty output ``on_empty`` decides; a refused or cut-off one keeps its
    error and no content, and fails as online's raise does.
    """
    for result in batch_results:
        if not result.success or result.parse_error is None:
            continue
        if json_mode:
            result.content = {"raw_response": result.text or "", "_parse_error": result.parse_error}
            result.error = None
            result.retriable = None
        elif result.content is None and result.error is None:
            result.content = []
        result.parse_error = None


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
