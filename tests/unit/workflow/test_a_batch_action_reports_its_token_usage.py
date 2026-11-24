"""A batch action reports the tokens its results used, as an online action reports its own.

Online clients count each call (`ResponseBuilder.record_usage_and_event`), and the executor
puts the action's sum on its metrics and `ActionCompleteEvent`. A batch is counted where its
results are retrieved (`retrieve_and_reconcile`), so every batch a check reads is in the sum:
the first batch, a retry, a repair round and a side batch alike.

A call made outside the action is not reported as the action's.
"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.services.shared import count_batch_usage, retrieve_and_reconcile
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.tooling.docs.run_tracker import RunTracker
from agent_actions.workflow.executor import ActionExecutor, ActionRunParams, ExecutorDependencies
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.output import ActionOutputManager
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ACTION = "agent_a"
CONFIG = {"kind": "llm", "model_vendor": "anthropic", "model_name": "m"}


def _answer(custom_id: str, usage: dict | None) -> BatchResult:
    return BatchResult(custom_id=custom_id, content={"a": 1}, success=True, usage=usage)


def _online_call(prompt: int, completion: int) -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=prompt, output_tokens=completion)
    )
    ResponseBuilder.record_usage_and_event(response, "anthropic", "m", 1.0, "r")


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
    deps.action_runner.execution_order = [ACTION]
    backend = deps.action_runner.storage_backend
    backend.has_disposition.return_value = False
    backend.get_failed_items.return_value = []
    backend.rows_collected.side_effect = [0, 2]
    backend.load_metadata.return_value = None
    deps.state_manager.get_status_details.return_value = {"status": ActionStatus.COMPLETED}
    deps.output_manager.resolve_correlated_input.return_value = None
    deps.batch_manager.check_batch_submission.return_value = None
    return deps


def _online_tokens(*usages: tuple[int, int]) -> dict | None:
    """An online action whose calls used *usages*, through the executor."""

    def run(*_args, **_kwargs):
        for prompt, completion in usages:
            _online_call(prompt, completion)
        return "/out"

    deps = _deps()
    deps.action_runner.run_action.side_effect = run
    params = ActionRunParams(ACTION, 0, CONFIG, True, datetime.now())
    with patch("agent_actions.workflow.executor.fire_event"):
        return ActionExecutor(deps)._execute_action_run(params).metrics.tokens


def _check(collect, tmp_path=None, status: str = "completed"):
    """A batch check that reads its batches as *collect* does; with *tmp_path*, into a run
    history."""

    def handle(*_args, **_kwargs):
        collect()
        return ("/out", status)

    deps = _deps()
    deps.batch_manager.handle_batch_agent.side_effect = handle
    executor = ActionExecutor(deps)
    tracker = None
    if tmp_path is not None:
        tracker = RunTracker(artefact_dir=tmp_path)
        executor.run_tracker = tracker
        executor.run_id = tracker.start_workflow_run(
            workflow_id="wf", workflow_name="wf", actions_total=1
        )
    with patch("agent_actions.workflow.executor.fire_event"):
        result = executor._handle_batch_check(
            action_name=ACTION, action_idx=0, action_config=CONFIG, start_time=datetime.now()
        )
    history = json.loads(tracker.runs_file.read_text()) if tracker is not None else None
    return result, history


def _batch_tokens(results: list[BatchResult]) -> dict | None:
    result, _ = _check(lambda: count_batch_usage("batch-1", results, kind="main", model="m"))
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


def test_a_call_made_before_the_action_does_not_reach_a_batch_action():
    _online_call(999, 999)

    assert _batch_tokens([_answer("r1", None)]) is None


def test_a_call_made_before_the_action_does_not_reach_an_action_that_used_none():
    _online_call(999, 999)

    assert _online_tokens() is None


def test_every_batch_a_check_reads_is_in_the_sum_and_one_read_twice_is_there_once():
    def collect():
        main = [_answer("r1", {"input_tokens": 10, "output_tokens": 20})]
        judged = [_answer("j_1", {"input_tokens": 1, "output_tokens": 2})]
        count_batch_usage("batch-1", main, kind="main", model="m")
        count_batch_usage("batch-2", judged, kind="judge", model="m")
        count_batch_usage("batch-1", main, kind="main", model="m")

    result, _ = _check(collect)

    assert result.metrics.tokens == {"input_tokens": 11, "output_tokens": 22, "total_tokens": 33}


def test_retrieving_a_batch_s_results_counts_what_they_used():
    provider = MagicMock()
    provider.retrieve_results.return_value = [
        _answer("r1", {"input_tokens": 3, "output_tokens": 4})
    ]

    result, _ = _check(
        lambda: retrieve_and_reconcile(
            provider, "batch-1", "/out", agent_config={"model_name": "m"}
        )
    )

    assert result.metrics.tokens == {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}


def test_a_check_that_reads_a_batch_and_waits_for_another_still_reports_what_it_read(tmp_path):
    """The batch is paid for whether or not this run writes the file."""
    results = [_answer("r1", {"input_tokens": 10, "output_tokens": 20})]

    _, history = _check(
        lambda: count_batch_usage("batch-1", results, kind="main", model="m"),
        tmp_path,
        status="in_progress",
    )

    (run,) = history["executions"]
    assert run["total_tokens"] == 30
    assert run["actions"][ACTION]["usage"]["by_kind"] == [
        {
            "kind": "main",
            "batch": True,
            "model": "m",
            "calls": 1,
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
    ]
    assert run["actions"][ACTION]["status"] == "running"


def test_a_check_that_completes_the_action_says_so_in_the_run_history(tmp_path):
    results = [_answer("r1", {"input_tokens": 10, "output_tokens": 20})]

    _, history = _check(
        lambda: count_batch_usage("batch-1", results, kind="main", model="m"), tmp_path
    )

    (run,) = history["executions"]
    assert run["actions"][ACTION]["status"] == "success"
    assert run["successful_actions"] == 1
    assert run["usage"] == {
        "calls": 1,
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


def test_a_check_that_fails_still_reports_the_batch_it_read(tmp_path):
    def collect():
        count_batch_usage(
            "batch-1",
            [_answer("r1", {"input_tokens": 10, "output_tokens": 20})],
            kind="main",
            model="m",
        )
        raise OSError("the store went away")

    deps = _deps()
    deps.batch_manager.handle_batch_agent.side_effect = lambda *_a, **_k: collect()
    executor = ActionExecutor(deps)
    tracker = RunTracker(artefact_dir=tmp_path)
    executor.run_tracker = tracker
    executor.run_id = tracker.start_workflow_run(
        workflow_id="wf", workflow_name="wf", actions_total=1
    )

    with pytest.raises(OSError, match="the store went away"):
        executor._handle_batch_check(
            action_name=ACTION, action_idx=0, action_config=CONFIG, start_time=datetime.now()
        )

    (run,) = json.loads(tracker.runs_file.read_text())["executions"]
    assert run["total_tokens"] == 30
    assert run["actions"][ACTION]["status"] == "failed"
