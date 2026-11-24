"""A sandbox command that an error stops still prints its one scenario line.

The line counts the faults of the calls the mock answered before the error. A command
stopped before the mock answered any call prints no line, and neither does a retry that
found nothing to retry.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.cli.args import RetryCommandArgs, RunCommandArgs
from agent_actions.cli.retry import RetryCommand
from agent_actions.cli.run import RunCommand
from agent_actions.config import sandbox
from agent_actions.utils.path_utils import reset_path_manager

LINE = "SANDBOX scenario happy: 1 errors, 0 rules broken, 0 batch results dropped"


@pytest.fixture(autouse=True)
def followed(tmp_path):
    """A sandbox command that follows the happy preset, loaded as a workflow load does."""
    reset_path_manager()
    with sandbox.sandbox_mode(True), sandbox.scenario_choice("happy"):
        sandbox.load_scenario(tmp_path, {"extract": None})
        yield
    reset_path_manager()


def _a_call_fails_then(error: BaseException | None):
    def workflow(*_args, **_kwargs):
        scenario = sandbox.scenario()
        scenario.next_attempt("extract", "r1")
        scenario.count("errors")
        if error is not None:
            raise error

    return workflow


def _run(tmp_path, execution) -> None:
    workflow = MagicMock()
    workflow.execution_order = ["extract"]
    tracker = MagicMock()
    tracker.start_workflow_run.return_value = "run-1"
    command = RunCommand(
        RunCommandArgs(agent="wf", user_code=None, use_tools=False, execution_mode="auto")
    )
    with (
        patch("agent_actions.cli.run.ProjectPathsFactory.create_project_paths") as paths,
        patch("agent_actions.cli.run.PromptValidator"),
        patch("agent_actions.cli.run.load_workflow", return_value=workflow),
        patch("agent_actions.cli.run.RunTracker", return_value=tracker),
        patch.object(command, "_run_workflow_execution", side_effect=execution),
    ):
        paths.return_value = MagicMock(io_dir=tmp_path)
        command.execute(project_root=tmp_path)


def _retry(tmp_path, one_pass) -> None:
    command = RetryCommand(RetryCommandArgs(agent="wf"))
    with (
        patch("agent_actions.cli.retry.ProjectPathsFactory.create_project_paths") as paths,
        patch("agent_actions.cli.retry.refuse_without_a_store"),
        patch.object(command, "_retry", side_effect=one_pass),
    ):
        paths.return_value = MagicMock(io_dir=tmp_path)
        command.execute(project_root=tmp_path)


def _scenario_lines(capsys) -> list[str]:
    out = capsys.readouterr().out
    return [line for line in out.splitlines() if line.startswith("SANDBOX scenario")]


@pytest.mark.parametrize("command", [_run, _retry])
def test_an_error_after_a_call_leaves_the_line_that_counts_it(tmp_path, capsys, command):
    with pytest.raises(RuntimeError, match="the store broke"):
        command(tmp_path, _a_call_fails_then(RuntimeError("the store broke")))

    assert _scenario_lines(capsys) == [LINE]


@pytest.mark.parametrize("command", [_run, _retry])
def test_an_interrupt_after_a_call_leaves_the_line_too(tmp_path, capsys, command):
    with pytest.raises(KeyboardInterrupt):
        command(tmp_path, _a_call_fails_then(KeyboardInterrupt()))

    assert _scenario_lines(capsys) == [LINE]


@pytest.mark.parametrize("command", [_run, _retry])
def test_an_error_before_any_call_leaves_no_line(tmp_path, capsys, command):
    def fails_at_once(*_args, **_kwargs):
        raise RuntimeError("the config is wrong")

    with pytest.raises(RuntimeError, match="the config is wrong"):
        command(tmp_path, fails_at_once)

    assert _scenario_lines(capsys) == []


def test_a_retry_that_finds_nothing_to_retry_prints_no_line(tmp_path, capsys):
    _retry(tmp_path, lambda *_args, **_kwargs: None)

    assert _scenario_lines(capsys) == []
