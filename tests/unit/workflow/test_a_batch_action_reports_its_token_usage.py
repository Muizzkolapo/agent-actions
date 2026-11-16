"""A batch action reports the tokens its results used, as an online action reports its own.

Online clients record each call's usage (`ResponseBuilder.record_usage_and_event`), which the
executor puts on the action's metrics and `ActionCompleteEvent`. Batch kept each result's usage
on the result and never reported it, so a batch action showed no tokens. It now reports the sum
over the results it writes, keyed as online keys it.

A usage an earlier call recorded is not reported as a later action's.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.services.processing_recovery import (
    finalize_batch_output,
    report_batch_usage,
)
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.llm.providers.usage_tracker import set_last_usage
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.processing.run_counts import counting
from agent_actions.workflow.executor import ActionExecutor, ActionRunParams, ExecutorDependencies
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.output import ActionOutputManager
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

STALE = {"input_tokens": 999, "output_tokens": 999, "total_tokens": 1998}


def _answer(custom_id: str, usage: dict | None) -> BatchResult:
    return BatchResult(custom_id=custom_id, content={"a": 1}, success=True, usage=usage)


def _deps():
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock(spec=ActionStateManager)
    deps.batch_manager = MagicMock(spec=BatchLifecycleManager)
    deps.skip_evaluator = MagicMock(spec=SkipEvaluator)
    deps.output_manager = MagicMock(spec=ActionOutputManager)
    deps.action_runner = MagicMock()
    deps.action_runner.staged_input_fingerprint.return_value = None
    deps.action_runner.workflow_name = "wf"
    deps.action_runner.get_action_folder.return_value = "/tmp/agent_io"
    deps.action_runner.execution_order = ["agent_a"]
    backend = deps.action_runner.storage_backend
    backend.has_disposition.return_value = False
    backend.get_failed_items.return_value = []
    backend.rows_collected.side_effect = [0, 2]
    deps.state_manager.get_status_details.return_value = {"status": ActionStatus.COMPLETED}
    deps.output_manager.resolve_correlated_input.return_value = None
    deps.batch_manager.check_batch_submission.return_value = None
    return deps


def _online_tokens(*usages: tuple[int, int]) -> dict | None:
    """An online action whose calls used *usages*, through the executor."""

    def run(*_args, **_kwargs):
        for prompt, completion in usages:
            response = SimpleNamespace(
                usage=SimpleNamespace(input_tokens=prompt, output_tokens=completion)
            )
            ResponseBuilder.record_usage_and_event(response, "anthropic", "m", 1.0, "r")
        return "/out"

    deps = _deps()
    deps.action_runner.run_action.side_effect = run
    params = ActionRunParams("agent_a", 0, {"kind": "llm"}, True, datetime.now())
    with patch("agent_actions.workflow.executor.fire_event"):
        return ActionExecutor(deps)._execute_action_run(params).metrics.tokens


def _batch_tokens(results: list[BatchResult]) -> dict | None:
    """A batch action whose collected results are *results*, through the executor."""

    def collect(*_args, **_kwargs):
        report_batch_usage(results)
        return ("/out", "completed")

    deps = _deps()
    deps.batch_manager.handle_batch_agent.side_effect = collect
    with patch("agent_actions.workflow.executor.fire_event"):
        result = ActionExecutor(deps)._handle_batch_check(
            action_name="agent_a",
            action_idx=0,
            action_config={"kind": "llm"},
            start_time=datetime.now(),
        )
    assert result.status == ActionStatus.COMPLETED
    return result.metrics.tokens


def test_a_batch_action_reports_its_tokens_as_online_reports_one_call():
    assert _batch_tokens([_answer("r1", {"input_tokens": 10, "output_tokens": 20})]) == (
        _online_tokens((10, 20))
    )


def test_the_tokens_are_summed_over_the_results():
    results = [
        _answer("r1", {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}),
        _answer("r2", {"input_tokens": 1, "output_tokens": 2}),
        _answer("r3", None),
        BatchResult(custom_id="r4", content=None, success=False, error="HTTP 400"),
    ]

    assert _batch_tokens(results) == {"input_tokens": 11, "output_tokens": 22, "total_tokens": 33}


def test_a_batch_whose_results_say_no_usage_reports_none():
    assert _batch_tokens([_answer("r1", None)]) is None


def test_an_earlier_call_s_usage_does_not_reach_a_batch_action():
    set_last_usage(STALE)

    assert _batch_tokens([_answer("r1", None)]) is None


def test_an_earlier_call_s_usage_does_not_reach_an_action_that_used_none():
    set_last_usage(STALE)

    assert _online_tokens() is None


def test_report_batch_usage_adds_to_the_open_counter_only():
    report_batch_usage([_answer("r1", {"input_tokens": 5, "output_tokens": 5})])
    with counting() as counts:
        report_batch_usage([_answer("r1", {"input_tokens": 1, "output_tokens": 2})])

    assert counts.tokens == {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}


def test_writing_a_batch_s_output_reports_its_results_usage(tmp_path):
    context = MagicMock()
    context.start_time = 0.0
    context.service._storage_backend = None
    context.service._convert_batch_results_to_workflow_format.return_value = ([], None, None)
    context.service._determine_output_path.return_value = str(tmp_path / "out.json")
    identity = MagicMock(batch_id="b1", file_name="pages.json")
    results = [_answer("r1", {"input_tokens": 3, "output_tokens": 4})]

    with (
        counting() as counts,
        patch("agent_actions.llm.batch.services.processing_recovery.fire_event"),
    ):
        finalize_batch_output(context, identity, results, context_map={})

    assert counts.tokens == {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}
