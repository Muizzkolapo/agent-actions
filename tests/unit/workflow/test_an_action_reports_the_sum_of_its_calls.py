"""An action's token usage is the sum over every call it made, in the run history too.

The executor read the usage of the last call from a context variable. A record is answered
in a thread of its own, in a copy of the context, so the executor read nothing, and
`artefact/runs.json` showed `total_tokens: 0` and no tokens on the action. Where it did read
a value it was the last call's, not the sum.
"""

from __future__ import annotations

import contextvars
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.tooling.docs.run_tracker import RunTracker
from agent_actions.workflow.executor import ActionExecutor, ActionRunParams, ExecutorDependencies
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.output import ActionOutputManager
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ACTION = "summarize"
MODEL = "claude-test"


def _call(prompt: int, completion: int) -> None:
    """One online model call that used *prompt* and *completion* tokens."""
    response = SimpleNamespace(usage=SimpleNamespace(input_tokens=prompt, output_tokens=completion))
    ResponseBuilder.record_usage_and_event(response, "anthropic", MODEL, 1.0, "request")


def _deps() -> MagicMock:
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


def _run(run_action, tmp_path=None):
    """Run the action once through the executor; with *tmp_path*, into a run history there."""
    deps = _deps()
    deps.action_runner.run_action.side_effect = run_action
    executor = ActionExecutor(deps)
    tracker = None
    if tmp_path is not None:
        tracker = RunTracker(artefact_dir=tmp_path)
        executor.run_tracker = tracker
        executor.run_id = tracker.start_workflow_run(
            workflow_id="wf", workflow_name="wf", actions_total=1
        )
    params = ActionRunParams(
        ACTION,
        0,
        {"kind": "llm", "model_vendor": "anthropic", "model_name": MODEL},
        True,
        datetime.now(),
    )
    with patch("agent_actions.workflow.executor.fire_event"):
        result = executor._execute_action_run(params)
    history = json.loads(tracker.runs_file.read_text()) if tracker is not None else None
    return result, history


def _two_records_each_in_its_own_thread(*_args, **_kwargs) -> str:
    """Two records, one call each, answered as the online strategy answers them."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(contextvars.copy_context().run, _call, prompt, completion)
            for prompt, completion in ((10, 20), (1, 2))
        ]
        for future in futures:
            future.result()
    return "/out"


def _two_calls_on_one_thread(*_args, **_kwargs) -> str:
    _call(10, 20)
    _call(1, 2)
    return "/out"


def test_an_action_with_two_records_reports_the_sum_of_both_calls():
    """Verification 7.1: 2 records, 1 LLM action, 2 calls; the sum, not the second call only."""
    result, _ = _run(_two_records_each_in_its_own_thread)

    assert result.metrics.tokens == {"input_tokens": 11, "output_tokens": 22, "total_tokens": 33}


def test_two_calls_made_one_after_the_other_are_summed_too():
    result, _ = _run(_two_calls_on_one_thread)

    assert result.metrics.tokens == {"input_tokens": 11, "output_tokens": 22, "total_tokens": 33}


def test_the_run_history_does_not_show_zero_tokens_for_a_run_that_made_calls(tmp_path):
    """Verification 7.3: `runs.json` holds the run's total and the action's tokens."""
    _, history = _run(_two_records_each_in_its_own_thread, tmp_path)

    (run,) = history["executions"]
    assert run["total_tokens"] == 33
    assert run["actions"][ACTION]["tokens"] == {
        "input_tokens": 11,
        "output_tokens": 22,
        "total_tokens": 33,
    }


def test_the_run_history_holds_the_action_s_usage_by_kind_and_the_run_s_total(tmp_path):
    _, history = _run(_two_records_each_in_its_own_thread, tmp_path)

    (run,) = history["executions"]
    total = {
        "calls": 2,
        "input_tokens": 11,
        "output_tokens": 22,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    assert run["usage"] == total
    assert run["actions"][ACTION]["usage"] == {
        **total,
        "by_kind": [{"kind": "main", "batch": False, "model": MODEL, **total}],
    }


def test_an_action_that_fails_still_reports_the_calls_it_made(tmp_path):
    def two_calls_then_a_failure(*_args, **_kwargs):
        _two_calls_on_one_thread()
        raise RuntimeError("the action failed")

    result, history = _run(two_calls_then_a_failure, tmp_path)

    (run,) = history["executions"]
    assert result.success is False
    assert run["actions"][ACTION]["status"] == "failed"
    assert run["total_tokens"] == 33


def test_an_action_run_twice_in_one_run_reports_both_executions_once(tmp_path):
    deps = _deps()
    deps.action_runner.run_action.side_effect = _two_calls_on_one_thread
    deps.action_runner.storage_backend.rows_collected.side_effect = [0, 2, 2, 4]
    executor = ActionExecutor(deps)
    tracker = RunTracker(artefact_dir=tmp_path)
    executor.run_tracker = tracker
    executor.run_id = tracker.start_workflow_run(
        workflow_id="wf", workflow_name="wf", actions_total=1
    )
    config = {"kind": "llm", "model_vendor": "anthropic", "model_name": MODEL}

    with patch("agent_actions.workflow.executor.fire_event"):
        for _ in range(2):
            executor._execute_action_run(ActionRunParams(ACTION, 0, config, True, datetime.now()))

    (run,) = json.loads(tracker.runs_file.read_text())["executions"]
    assert run["actions"][ACTION]["usage"]["calls"] == 4
    assert run["total_tokens"] == 66
