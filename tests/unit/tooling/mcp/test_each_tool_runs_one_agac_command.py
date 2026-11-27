"""An MCP tool call becomes one `agac` command line, and a real one is refused by default."""

from pathlib import Path

import pytest

from agent_actions.tooling.mcp import tools as mcp_tools
from agent_actions.tooling.mcp.tools import (
    MAX_OUTPUT_CHARS,
    Context,
    ToolRefused,
    call_tool,
    check_arguments,
    list_workflows,
    refuse_a_real_call,
    tools_by_name,
)

TOOLS = tools_by_name()
SANDBOX_ONLY = Context(project_root=Path("."))
REAL_ALLOWED = Context(project_root=Path("."), allow_real_runs=True)


def _argv(name: str, **args) -> list[str]:
    return TOOLS[name].command(args)


def test_a_run_is_a_sandbox_run_that_waits_unless_told_otherwise():
    assert _argv("run_workflow", workflow="wf") == [
        "run",
        "--workflow=wf",
        "--sandbox",
        "--wait",
    ]
    assert _argv("run_workflow", workflow="wf", sandbox=False, wait=False) == [
        "run",
        "--workflow=wf",
    ]


def test_a_filtered_rerun_passes_its_filter_and_a_dry_run_does_not_wait():
    argv = _argv(
        "run_workflow",
        workflow="wf",
        rerun=["classify"],
        where='classify.label == "other"',
        dry_run=True,
    )

    assert argv == [
        "run",
        "--workflow=wf",
        "--sandbox",
        "--rerun=classify",
        '--where=classify.label == "other"',
        "--dry-run",
    ]


def test_a_scenario_goes_only_with_a_sandbox_run():
    assert "--scenario=chaos" in _argv("run_workflow", workflow="wf", scenario="chaos")
    assert "--scenario=chaos" not in _argv(
        "run_workflow", workflow="wf", scenario="chaos", sandbox=False
    )


def test_a_value_is_bound_to_its_option_so_it_cannot_be_read_as_another():
    argv = _argv("workflow_status", workflow="--fresh")

    assert argv == ["status", "--workflow=--fresh", "--sandbox", "--json"]


@pytest.mark.parametrize(
    ("name", "args", "argv"),
    [
        (
            "retry_workflow",
            {"from_action": "a", "all": True},
            ["retry", "--workflow=wf", "--sandbox", "--from=a", "--all"],
        ),
        (
            "sandbox_check",
            {"scenario": "chaos"},
            ["sandbox", "check", "--workflow=wf", "--scenario=chaos"],
        ),
        ("inspect_workflow", {}, ["inspect", "--workflow=wf", "--sandbox"]),
        (
            "dispositions",
            {"quarantined": True},
            ["dispositions", "--workflow=wf", "--sandbox", "--quarantined"],
        ),
        ("dispositions", {"sandbox": False}, ["dispositions", "--workflow=wf", "--json"]),
        (
            "records",
            {"action": "a", "field": "content.x"},
            ["records", "--workflow=wf", "--sandbox", "--action=a", "--field=content.x"],
        ),
        (
            "traces",
            {"action": "a"},
            ["traces", "--workflow=wf", "--sandbox", "--action=a", "--json"],
        ),
        ("usage", {}, ["usage", "--workflow=wf", "--sandbox", "--json"]),
        (
            "expect_report",
            {"action": "a"},
            ["expect", "report", "--workflow=wf", "--sandbox", "--action=a", "--json"],
        ),
        ("workflow_schema", {}, ["schema", "--workflow=wf", "--json"]),
        ("export_outputs", {"action": "a"}, ["export", "--workflow=wf", "--action=a"]),
    ],
)
def test_each_tool_builds_the_command_of_its_name(name, args, argv):
    assert _argv(name, workflow="wf", **args) == argv


@pytest.mark.parametrize("name", ["run_workflow", "retry_workflow"])
def test_a_real_run_is_refused_unless_the_server_allows_real_runs(name):
    with pytest.raises(ToolRefused, match="agac mcp --allow-real-runs"):
        refuse_a_real_call(TOOLS[name], {"workflow": "wf", "sandbox": False}, SANDBOX_ONLY)

    refuse_a_real_call(TOOLS[name], {"workflow": "wf", "sandbox": False}, REAL_ALLOWED)
    refuse_a_real_call(TOOLS[name], {"workflow": "wf"}, SANDBOX_ONLY)


def test_an_export_has_no_sandbox_form_so_it_is_always_a_real_call():
    with pytest.raises(ToolRefused, match="It has no sandbox form"):
        refuse_a_real_call(TOOLS["export_outputs"], {"workflow": "wf"}, SANDBOX_ONLY)

    refuse_a_real_call(TOOLS["export_outputs"], {"workflow": "wf"}, REAL_ALLOWED)


def test_reading_what_real_runs_stored_is_never_refused():
    for name in ("workflow_status", "dispositions", "records", "usage", "expect_report"):
        refuse_a_real_call(TOOLS[name], {"workflow": "wf", "sandbox": False}, SANDBOX_ONLY)


@pytest.mark.parametrize(
    ("args", "said"),
    [
        ({"workflow": "wf", "nope": 1}, "takes no argument named nope"),
        ({}, "needs workflow"),
        ({"workflow": ""}, "needs workflow"),
        ({"workflow": "wf", "fresh": "yes"}, "'fresh' must be a boolean"),
        ({"workflow": "wf", "record_limit": True}, "'record_limit' must be a whole number"),
        ({"workflow": "wf", "rerun": "classify"}, "'rerun' must be a list of strings"),
        ({"workflow": "wf", "rerun": [1]}, "'rerun' must be a list of strings"),
        ({"workflow": 7}, "'workflow' must be a string"),
    ],
)
def test_arguments_the_schema_does_not_allow_are_refused_by_name(args, said):
    with pytest.raises(ToolRefused, match=said):
        check_arguments(TOOLS["run_workflow"], args)


def test_every_tool_s_schema_closes_its_arguments_and_requires_what_it_needs():
    for tool in TOOLS.values():
        schema = tool.schema()["inputSchema"]
        assert schema["additionalProperties"] is False, tool.name
        assert set(schema["required"]) <= set(schema["properties"]), tool.name
        assert all("description" in spec for spec in schema["properties"].values()), tool.name


class _Done:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.fixture
def ran(monkeypatch):
    """Stand in for the `agac` process; holds each command line and what it found on disk."""
    calls: list[dict] = []
    answer = {"done": _Done()}

    def run(command, **options):
        listed = [part.split("=", 1)[1] for part in command if part.startswith("--records=")]
        calls.append(
            {
                "argv": command[3:],
                "cwd": options["cwd"],
                "records": Path(listed[0]).read_text() if listed else None,
            }
        )
        return answer["done"]

    monkeypatch.setattr(mcp_tools.subprocess, "run", run)
    return calls, answer


def test_listed_records_reach_the_command_as_a_file_of_ids(ran, tmp_path):
    calls, _ = ran
    context = Context(project_root=tmp_path)

    call_tool(
        TOOLS["run_workflow"], {"workflow": "wf", "rerun": ["a"], "records": ["g1", "g2"]}, context
    )

    assert calls[0]["records"] == "g1\ng2\n"
    assert calls[0]["cwd"] == tmp_path


@pytest.mark.parametrize(
    ("code", "is_error"), [(0, False), (3, False), (4, False), (1, True), (2, True), (5, True)]
)
def test_a_run_s_exit_code_is_an_outcome_and_only_a_failed_command_is_an_error(
    ran, tmp_path, code, is_error
):
    _, answer = ran
    answer["done"] = _Done(returncode=code, stdout="out")

    outcome = call_tool(TOOLS["run_workflow"], {"workflow": "wf"}, Context(project_root=tmp_path))

    assert (outcome.exit_code, outcome.is_error) == (code, is_error)
    assert outcome.text.startswith("$ agac run --workflow=wf --sandbox --wait\nexit code ")


def test_a_check_whose_values_do_not_hold_is_a_result_not_an_error(ran, tmp_path):
    _, answer = ran
    answer["done"] = _Done(returncode=1, stdout="classify success: expected 4, got 3")

    outcome = call_tool(TOOLS["sandbox_check"], {"workflow": "wf"}, Context(project_root=tmp_path))

    assert not outcome.is_error
    assert "a value does not hold" in outcome.text


def test_a_json_tool_returns_its_json_without_the_notices_printed_beside_it(ran, tmp_path):
    _, answer = ran
    answer["done"] = _Done(
        stdout='SANDBOX: reading the sandbox output\n{"run_status": "SUCCESS"}\n',
        stderr="Loaded status",
    )

    outcome = call_tool(
        TOOLS["workflow_status"], {"workflow": "wf"}, Context(project_root=tmp_path)
    )

    assert outcome.text.endswith('\n\n{"run_status": "SUCCESS"}')


def test_records_are_cut_to_the_limit_with_the_count_of_them_all(ran, tmp_path):
    _, answer = ran
    answer["done"] = _Done(stdout='[{"n": 1}, {"n": 2}, {"n": 3}]')

    outcome = call_tool(
        TOOLS["records"], {"workflow": "wf", "limit": 2}, Context(project_root=tmp_path)
    )

    assert "3 records in all; the first 2 are shown" in outcome.text
    assert '"n": 2' in outcome.text and '"n": 3' not in outcome.text


def test_a_long_output_keeps_its_start_and_its_end(ran, tmp_path):
    _, answer = ran
    answer["done"] = _Done(stdout="START" + "x" * (MAX_OUTPUT_CHARS * 2) + "END")

    outcome = call_tool(TOOLS["run_workflow"], {"workflow": "wf"}, Context(project_root=tmp_path))

    assert "START" in outcome.text and outcome.text.endswith("END")
    assert "characters left out" in outcome.text
    assert len(outcome.text) < MAX_OUTPUT_CHARS + 500


def test_a_call_that_outlasts_the_timeout_says_the_run_can_be_resumed(monkeypatch, tmp_path):
    def run(command, **options):
        raise mcp_tools.subprocess.TimeoutExpired(command, options["timeout"])

    monkeypatch.setattr(mcp_tools.subprocess, "run", run)

    outcome = call_tool(
        TOOLS["run_workflow"],
        {"workflow": "wf"},
        Context(project_root=tmp_path, timeout_seconds=5),
    )

    assert outcome.is_error
    assert "no result after 5 seconds" in outcome.text


def test_the_workflows_of_a_project_are_listed_by_their_config_files(tmp_path):
    for name in ("b_flow", "a_flow"):
        folder = tmp_path / "agent_workflow" / name / "agent_config"
        folder.mkdir(parents=True)
        (folder / f"{name}.yml").write_text("name: x\n")

    assert list_workflows(tmp_path) == [
        {"workflow": "a_flow", "config": "agent_workflow/a_flow/agent_config/a_flow.yml"},
        {"workflow": "b_flow", "config": "agent_workflow/b_flow/agent_config/b_flow.yml"},
    ]
