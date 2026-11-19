"""`-w` is the workflow and `-A` the action in every command; `-a` is never both.

`traces`, `records` and `preview` read `-a` as the action while every other
command read it as the workflow. They still take it as the action, with a
warning on stderr that says what to type.
"""

import json

import click
import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

WORKFLOW = "wf"
ACTION = "summarize"
# Until `-a` stops naming the action in these, it cannot name the workflow.
ACTION_WAS_A = {"traces", "records", "preview"}
WORKFLOW_PARAMS = {"agent", "agent_opt", "agent_name", "workflow"}


def _commands(group: click.Group, path: tuple[str, ...] = ()):
    for name, command in sorted(group.commands.items()):
        if isinstance(command, click.Group):
            yield from _commands(command, (*path, name))
        yield " ".join((*path, name)), command


def _option(command: click.Command, *names: str) -> click.Option | None:
    return next(
        (p for p in command.params if isinstance(p, click.Option) and p.name in names), None
    )


WITH_A_WORKFLOW = {
    path: command for path, command in _commands(cli) if _option(command, *WORKFLOW_PARAMS)
}
WITH_AN_ACTION = {
    path: command for path, command in _commands(cli) if _option(command, "action", "action_name")
}


def test_the_commands_that_take_a_workflow_are_the_ones_known():
    assert set(WITH_A_WORKFLOW) == {
        "batch retrieve",
        "batch status",
        "clean",
        "dispositions",
        "expect list",
        "expect report",
        "inspect",
        "inspect action",
        "inspect context",
        "preview",
        "records",
        "retry",
        "run",
        "schema",
        "status",
        "traces",
        "validate-udfs",
    }


@pytest.mark.parametrize("path", sorted(WITH_A_WORKFLOW))
def test_every_command_that_takes_a_workflow_takes_it_as_w_workflow_and_agent(path):
    option = _option(WITH_A_WORKFLOW[path], *WORKFLOW_PARAMS)

    assert option is not None
    assert {"-w", "--workflow", "--agent"} <= set(option.opts)
    assert ("-a" in option.opts) == (path not in ACTION_WAS_A)


@pytest.mark.parametrize("path", sorted(WITH_AN_ACTION))
def test_every_action_option_has_the_short_flag_capital_a(path):
    option = _option(WITH_AN_ACTION[path], "action", "action_name")

    assert option is not None
    assert {"-A", "--action"} <= set(option.opts)
    assert "-a" not in option.opts


def test_no_command_gives_a_w_or_capital_a_another_meaning():
    for path, command in _commands(cli):
        for param in command.params:
            if not isinstance(param, click.Option):
                continue
            if "-w" in param.opts:
                assert param.name in WORKFLOW_PARAMS, path
            if "-A" in param.opts:
                assert param.name in {"action", "action_name"}, path
            if "-a" in param.opts and param.name not in WORKFLOW_PARAMS:
                assert path in ACTION_WAS_A and param.hidden, path


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "agent_actions.yml").write_text("default_agent_config: {}\n")
    workflow = tmp_path / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(f"name: {WORKFLOW}\nactions: []\n")
    store = workflow / "agent_io" / "store"
    store.mkdir(parents=True)
    backend = SQLiteBackend(str(store / f"{WORKFLOW}.db"), workflow_name=WORKFLOW)
    backend.initialize()
    backend.write_prompt_trace(ACTION, "tid-1", "Page alpha prompt.")
    backend.write_target(
        ACTION,
        "a.json",
        [{"source_guid": "guid-0", "content": {ACTION: {"summary": "Alpha."}}}],
        force_full=True,
    )
    backend.set_disposition(
        ACTION,
        "guid-9",
        "failed",
        reason="boom",
        relative_path="a.json",
        input_snapshot=json.dumps({"source_guid": "guid-9"}),
    )
    backend.close()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run(*args: str):
    return CliRunner().invoke(cli, list(args))


@pytest.mark.parametrize("flag", ["--action", "-A"])
def test_traces_w_workflow_action_prints_the_traces_and_no_warning(project, flag):
    result = _run("traces", "-w", WORKFLOW, flag, ACTION)

    assert result.exit_code == 0, result.output
    assert "Page alpha prompt." in result.stdout
    assert "deprecated" not in result.stderr


def test_traces_takes_agent_for_the_workflow(project):
    result = _run("traces", "--agent", WORKFLOW, "-A", ACTION)

    assert result.exit_code == 0, result.output
    assert "Page alpha prompt." in result.stdout


@pytest.mark.parametrize(
    ("command", "shown"),
    [
        (("traces",), "Page alpha prompt."),
        (("records",), "Alpha."),
        (("preview", "-f", "raw"), "Alpha."),
    ],
    ids=["traces", "records", "preview"],
)
def test_a_for_the_action_still_works_and_says_on_stderr_what_to_type(project, command, shown):
    name, *rest = command
    result = _run(name, "-w", WORKFLOW, "-a", ACTION, *rest)

    assert result.exit_code == 0, result.output
    assert shown in result.stdout
    assert "deprecated" not in result.stdout
    assert f"-a is deprecated in 'agac {name}'" in result.stderr
    assert "-A" in result.stderr and "--action" in result.stderr and "-w" in result.stderr


def test_records_a_workflow_prints_a_deprecation_warning(project):
    """`agac records -a <wf>`: the workflow typed where this command reads the action."""
    result = _run("records", "-a", WORKFLOW)

    assert result.exit_code != 0
    assert "-a is deprecated" in result.stderr
    assert "-w" in result.stderr
    assert "Missing option '-w'" in result.stderr


def test_records_a_workflow_w_workflow_does_not_end_in_a_bare_empty_result(project):
    result = _run("records", "-a", WORKFLOW, "-w", WORKFLOW, "--snapshots")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []
    assert "-a is deprecated" in result.stderr
    assert "-w" in result.stderr


def test_traces_without_an_action_names_the_option_it_lacks(project):
    result = _run("traces", "-w", WORKFLOW)

    assert result.exit_code == 2
    assert "Missing option '-A' / '--action'" in result.stderr


def test_an_action_given_both_ways_is_refused(project):
    result = _run("traces", "-w", WORKFLOW, "-a", ACTION, "-A", "classify")

    assert result.exit_code == 2
    assert "-a" in result.stderr and "-A" in result.stderr
