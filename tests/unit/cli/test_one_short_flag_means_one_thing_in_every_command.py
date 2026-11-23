"""`-w` and `-a` are the workflow and `-A` the action in every command.

`traces`, `records` and `preview` read `-a` as the action while every other
command read it as the workflow. Now `-a` names the workflow there too.
"""

import json

import click
import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

WORKFLOW = "wf"
ACTION = "summarize"
WORKFLOW_PARAMS = {"agent", "agent_opt", "agent_name", "workflow"}


def _commands(group: click.Group, path: tuple[str, ...] = ()):
    ctx = click.Context(group)
    for name in group.list_commands(ctx):
        command = group.get_command(ctx, name)
        assert command is not None
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
        "export",
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
        "usage",
        "validate-udfs",
    }


@pytest.mark.parametrize("path", sorted(WITH_A_WORKFLOW))
def test_every_command_that_takes_a_workflow_takes_it_as_w_workflow_and_a(path):
    option = _option(WITH_A_WORKFLOW[path], *WORKFLOW_PARAMS)

    assert option is not None
    assert {"-w", "--workflow", "-a"} <= set(option.opts)
    assert "--agent" not in option.opts


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
            if "-a" in param.opts:
                assert param.name in WORKFLOW_PARAMS, path


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
    assert result.stderr == ""


def test_traces_takes_workflow_for_the_workflow(project):
    result = _run("traces", "--workflow", WORKFLOW, "-A", ACTION)

    assert result.exit_code == 0, result.output
    assert "Page alpha prompt." in result.stdout


@pytest.mark.parametrize("path", sorted(WITH_A_WORKFLOW))
def test_agent_is_no_such_option(path):
    result = _run(*path.split(), "--agent", WORKFLOW)

    assert result.exit_code == 2
    assert "No such option: --agent" in result.stderr


@pytest.mark.parametrize(
    ("command", "shown"),
    [
        (("traces",), "Page alpha prompt."),
        (("records",), "Alpha."),
        (("preview", "-f", "raw"), "Alpha."),
    ],
    ids=["traces", "records", "preview"],
)
def test_a_names_the_workflow_and_capital_a_the_action(project, command, shown):
    name, *rest = command
    result = _run(name, "-a", WORKFLOW, "-A", ACTION, *rest)

    assert result.exit_code == 0, result.output
    assert shown in result.stdout
    assert "deprecated" not in result.output


@pytest.mark.parametrize("name", ["records", "preview"])
def test_a_alone_names_the_workflow(project, name):
    result = _run(name, "-a", WORKFLOW)

    assert result.exit_code == 0, result.output
    assert "deprecated" not in result.output


def test_records_a_workflow_snapshots_prints_the_failed_record(project):
    result = _run("records", "-a", WORKFLOW, "--snapshots")

    assert result.exit_code == 0, result.output
    assert [r["record_id"] for r in json.loads(result.stdout)] == ["guid-9"]


def test_traces_without_an_action_names_the_option_it_lacks(project):
    result = _run("traces", "-a", WORKFLOW)

    assert result.exit_code == 2
    assert "Missing option '-A' / '--action'" in result.stderr


def test_help_prints_no_warning(project):
    result = _run("traces", "--help")

    assert result.exit_code == 0
    assert result.stderr == ""
    assert "-A, --action" in result.stdout
