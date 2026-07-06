"""The prompt trace must record the action's model name for every run mode."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.config.types import RunMode
from agent_actions.input.preprocessing.filtering.evaluator import GuardResult
from agent_actions.processing.prepared_task import PreparationContext
from agent_actions.processing.task_preparer import TaskPreparer


def _context(mode: RunMode, agent_config: dict | None = None) -> MagicMock:
    ctx = MagicMock(spec=PreparationContext)
    ctx.agent_name = "score"
    if agent_config is None:
        agent_config = {"model_name": "gpt-4o-mini", "model_vendor": "openai"}
    ctx.agent_config = agent_config
    ctx.mode = mode
    ctx.is_first_stage = False
    ctx.source_data = None
    ctx.agent_indices = None
    ctx.dependency_configs = None
    ctx.workflow_metadata = None
    ctx.version_context = None
    ctx.file_path = None
    ctx.output_directory = None
    ctx.storage_backend = MagicMock()
    ctx.current_item = None
    ctx.record_index = 0
    return ctx


def _prepare_and_get_trace_kwargs(preparer: TaskPreparer, ctx: MagicMock, item: dict) -> dict:
    with (
        patch.object(preparer, "_normalize_input", return_value=(item, "sg-1", item)),
        patch.object(preparer, "_load_full_context", return_value={"quality_score": 0.9}),
        patch.object(preparer, "_evaluate_guard", return_value=GuardResult.warned()),
        patch.object(
            preparer,
            "_render_prompt",
            return_value=MagicMock(
                formatted_prompt="p", llm_context={}, passthrough_fields={}, prompt_context={}
            ),
        ),
    ):
        preparer.prepare(item, ctx)

    ctx.storage_backend.write_prompt_trace.assert_called_once()
    return ctx.storage_backend.write_prompt_trace.call_args.kwargs


@pytest.mark.parametrize("mode", [RunMode.ONLINE, RunMode.BATCH])
def test_prompt_trace_persists_model_name_for_both_modes(mode):
    preparer = TaskPreparer()
    ctx = _context(mode)
    item = {"content": {"quality_score": 0.9}, "source_guid": "sg-1"}
    kwargs = _prepare_and_get_trace_kwargs(preparer, ctx, item)
    assert kwargs["model_name"] == "gpt-4o-mini", (
        f"model_name not persisted: {kwargs['model_name']!r}"
    )
    assert kwargs["model_vendor"] == "openai"


def test_prompt_trace_falls_back_to_model_alias_when_model_name_absent():
    preparer = TaskPreparer()
    ctx = _context(RunMode.ONLINE, agent_config={"model": "gpt-4o-mini", "model_vendor": "openai"})
    item = {"content": {"quality_score": 0.9}, "source_guid": "sg-1"}
    kwargs = _prepare_and_get_trace_kwargs(preparer, ctx, item)
    assert kwargs["model_name"] == "gpt-4o-mini", (
        f"model alias not used as model_name fallback: {kwargs['model_name']!r}"
    )
