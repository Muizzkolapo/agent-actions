"""A command a sandbox run tells you to run names --sandbox, so it acts on sandbox output."""

import io

import pytest
from rich.console import Console

from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.exit_codes import RunOutcome
from agent_actions.cli.retry import RetryCommand
from agent_actions.cli.retry_filter import RetryFilterCommand
from agent_actions.cli.run import RunCommand
from agent_actions.config import sandbox


class _Waiting:
    def get_batch_submitted_actions(self, execution_order):
        return ["classify"]


def _retry(buffer):
    command = object.__new__(RetryCommand)
    command.agent_name = "wf"
    command.console = Console(file=buffer, width=200)
    command.args = RetryCommandArgs(agent="wf")
    return command


@pytest.mark.parametrize("outcome", [RunOutcome.PAUSED_FOR_BATCH, RunOutcome.PAUSED])
@pytest.mark.parametrize("active", [True, False])
def test_a_paused_retry_names_the_flag_only_in_a_sandbox(outcome, active):
    buffer = io.StringIO()
    with sandbox.sandbox_mode(active):
        _retry(buffer)._report(outcome, _Waiting(), ["classify"])

    assert ("agac run -w wf --sandbox" in buffer.getvalue()) is active


def test_a_paused_rerun_that_waits_names_no_command_to_run():
    buffer = io.StringIO()
    command = _retry(buffer)
    command.args = RetryCommandArgs(agent="wf", collected_after=True)

    command._report(RunOutcome.PAUSED_FOR_BATCH, _Waiting(), ["classify"])

    said = " ".join(buffer.getvalue().split())
    assert "batch job(s) submitted for: classify. Waiting for them to be collected." in said
    assert "agac run" not in said


@pytest.mark.parametrize("active", [True, False])
def test_the_wait_timeout_names_the_flag_only_in_a_sandbox(active, capsys):
    command = object.__new__(RunCommand)
    command.args = type("Args", (), {"agent": "wf"})()
    command._open_batches = ["classify"]
    with sandbox.sandbox_mode(active):
        command._stop_waiting(0.0)

    assert ("agac run -w wf --sandbox --wait" in capsys.readouterr().out) is active


@pytest.mark.parametrize("active", [True, False])
def test_the_filter_refusal_names_the_flag_only_in_a_sandbox(active):
    command = object.__new__(RetryFilterCommand)
    command.agent_name = "wf"
    with sandbox.sandbox_mode(active):
        refusal = command._refusal(("classify", "r1"), None, ["classify"])

    assert ("--quarantined --sandbox" in refusal) is active


@pytest.mark.parametrize(
    ("wait", "then"), [(True, "--wait checks them again."), (False, "Run again")]
)
def test_a_paused_run_that_waits_says_it_waits(wait, then, capsys):
    from types import SimpleNamespace

    command = object.__new__(RunCommand)
    command.args = SimpleNamespace(agent="wf", wait=wait)
    state = SimpleNamespace(
        get_summary=lambda: {"completed": 3},
        get_batch_submitted_actions=lambda order: ["classify"],
    )
    workflow = SimpleNamespace(
        services=SimpleNamespace(core=SimpleNamespace(state_manager=state)),
        execution_order=["classify"],
    )

    command._report(RunOutcome.PAUSED_FOR_BATCH, workflow)

    said = capsys.readouterr().out
    assert "batch job(s) submitted for: classify (completed: 3)." in said
    assert then in said
