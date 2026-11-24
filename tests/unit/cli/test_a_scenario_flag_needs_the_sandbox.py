"""`--scenario` names the scenario the sandbox mock follows; it needs `--sandbox`.

A command a run prints to go on with the run or to retry it names the `--scenario` given,
and a read command it prints does not, as no read command takes it.
"""

from __future__ import annotations

import io

import click
import pytest
from click.testing import CliRunner
from rich.console import Console

from agent_actions.cli.cli_decorators import sandbox_option, scenario_option
from agent_actions.cli.exit_codes import RunOutcome
from agent_actions.cli.retry import RetryCommand
from agent_actions.config import sandbox


def _command(seen: list):
    @click.command()
    @sandbox_option()
    @scenario_option()
    def command():
        seen.append((sandbox.is_active(), sandbox._follows_scenario, sandbox._scenario_flag))

    return command


def test_a_scenario_without_the_sandbox_is_a_usage_error():
    seen: list = []

    result = CliRunner().invoke(_command(seen), ["--scenario", "chaos"])

    assert result.exit_code == 2
    assert "--scenario needs --sandbox" in result.output
    assert seen == []


@pytest.mark.parametrize(
    ("args", "flag"),
    [(["--sandbox"], None), (["--sandbox", "--scenario", "chaos"], "chaos"), ([], None)],
)
def test_the_command_follows_the_scenario_given_and_forgets_it_after(args, flag):
    seen: list = []

    result = CliRunner().invoke(_command(seen), args)

    assert result.exit_code == 0, result.output
    assert seen == [(bool(args), True, flag)]
    assert (sandbox._follows_scenario, sandbox._scenario_flag) == (False, None)


def test_a_scenario_loads_only_for_a_command_that_follows_one(tmp_path):
    with sandbox.sandbox_mode(True):
        sandbox.load_scenario(tmp_path, {"extract": None})
        assert sandbox.scenario() is None
        with sandbox.scenario_choice("chaos"):
            sandbox.load_scenario(tmp_path, {"extract": None})
            assert sandbox.scenario() is not None
            assert sandbox.scenario().name == "chaos"
        assert sandbox.scenario() is None


@pytest.mark.parametrize(
    ("source", "named"),
    [
        (None, " --sandbox"),
        ("chaos", " --sandbox --scenario chaos"),
        ("my faults.yml", " --sandbox --scenario 'my faults.yml'"),
    ],
)
def test_a_printed_run_or_retry_names_the_scenario_given(source, named):
    with sandbox.sandbox_mode(True), sandbox.scenario_choice(source):
        assert sandbox.run_flags() == named
        assert sandbox.flag() == " --sandbox"
    assert sandbox.run_flags() == ""


def test_a_paused_retry_names_the_scenario_given():
    buffer = io.StringIO()
    command = object.__new__(RetryCommand)
    command.agent_name = "wf"
    command.console = Console(file=buffer, width=200)

    with sandbox.sandbox_mode(True), sandbox.scenario_choice("chaos"):
        command._report(RunOutcome.PAUSED, None, [])

    assert "agac run -a wf --sandbox --scenario chaos" in buffer.getvalue()
