"""An MCP tool call becomes one `agac` command line, and a real one is refused by default."""

import json
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


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("run_workflow", {"scenario": ".env"}),
        ("run_workflow", {"scenario": "/etc/passwd"}),
        ("retry_workflow", {"scenario": "../outside.yml"}),
        ("inspect_workflow", {"scenario": "agent_io/kept.yml"}),
        ("sandbox_check", {"expected": ".env"}),
        ("sandbox_check", {"expected": "/home/someone/.aws/credentials"}),
        ("run_workflow", {"scenario": "deploy/secrets.yml"}),
        ("sandbox_check", {"expected": "docker-compose.yml"}),
    ],
)
def test_a_scenario_or_expectations_file_must_be_a_yaml_file_of_the_project(
    ran, tmp_path, name, args
):
    # The CLI quotes the line a YAML file fails on, so another file would be read through it.
    calls, _ = ran

    with pytest.raises(ToolRefused, match=r"sandbox\*\.yml file of the project"):
        call_tool(TOOLS[name], {"workflow": "wf", **args}, Context(project_root=tmp_path))

    assert calls == []


@pytest.mark.parametrize(
    "scenario", ["happy", "chaos", "sandbox.yml", "scenarios/sandbox_late.yaml"]
)
def test_a_named_scenario_or_a_yaml_file_of_the_project_is_taken(ran, tmp_path, scenario):
    calls, _ = ran

    call_tool(TOOLS["run_workflow"], {"workflow": "wf", "scenario": scenario}, Context(tmp_path))

    assert f"--scenario={scenario}" in calls[0]["argv"]


@pytest.mark.parametrize("limit", [0, -1])
def test_a_limit_below_one_is_refused(limit):
    with pytest.raises(ToolRefused, match="'limit' must be 1 or more"):
        check_arguments(TOOLS["records"], {"workflow": "wf", "limit": limit})


@pytest.mark.parametrize("value", ["a\x00b", "a\ud800b"])
def test_a_nul_or_an_unpaired_surrogate_is_refused(value):
    with pytest.raises(ToolRefused, match="NUL or an unpaired surrogate"):
        check_arguments(TOOLS["records"], {"workflow": value})


def test_an_argument_sent_as_null_is_left_out(ran, tmp_path):
    calls, _ = ran

    call_tool(
        TOOLS["run_workflow"],
        {"workflow": "wf", "where": None, "scenario": None},
        Context(project_root=tmp_path),
    )

    assert calls[0]["argv"] == ["run", "--workflow=wf", "--sandbox", "--wait"]


def test_the_command_speaks_utf_8_whatever_the_locale(monkeypatch, tmp_path):
    seen = {}

    def run(command, **options):
        seen.update(options)
        return _Done()

    monkeypatch.setattr(mcp_tools.subprocess, "run", run)

    call_tool(TOOLS["usage"], {"workflow": "wf"}, Context(project_root=tmp_path))

    assert (seen["encoding"], seen["errors"]) == ("utf-8", "replace")
    assert seen["env"]["PYTHONIOENCODING"] == "utf-8"


@pytest.mark.parametrize("folder", ["/home/someone/other/tools", "../other/tools", "agent_io"])
def test_user_code_must_be_a_folder_of_the_project(ran, tmp_path, folder):
    calls, _ = ran

    with pytest.raises(ToolRefused, match="'user_code' must be a folder of the project"):
        call_tool(
            TOOLS["run_workflow"], {"workflow": "wf", "user_code": folder}, Context(tmp_path)
        )

    assert calls == []


def test_user_code_in_the_project_is_passed_on(ran, tmp_path):
    calls, _ = ran

    call_tool(TOOLS["run_workflow"], {"workflow": "wf", "user_code": "tools"}, Context(tmp_path))

    assert "--user-code=tools" in calls[0]["argv"]


@pytest.mark.parametrize("listed", [["a\nb"], ["a\rb"], ["#a"], ["  "]])
def test_a_record_id_that_would_read_as_another_line_is_refused(listed):
    with pytest.raises(ToolRefused, match="each id in 'records' must be one line"):
        check_arguments(TOOLS["run_workflow"], {"workflow": "wf", "records": listed})


def test_a_real_run_does_not_wait_for_a_batch_unless_told_to():
    assert "--wait" not in _argv("run_workflow", workflow="wf", sandbox=False)
    assert "--wait" in _argv("run_workflow", workflow="wf", sandbox=False, wait=True)
    assert "--wait" in _argv("run_workflow", workflow="wf")


def test_traces_keep_the_newest_when_they_are_cut(ran, tmp_path):
    # Traces are stored oldest first; the newest are the run just made.
    _, answer = ran
    traces = [{"record_id": f"r{n}"} for n in range(5)]
    answer["done"] = _Done(stdout=json.dumps(traces))

    outcome = call_tool(
        TOOLS["traces"], {"workflow": "wf", "action": "a", "limit": 2}, Context(tmp_path)
    )

    assert "5 records in all; the last 2 (newest) are shown" in outcome.text
    assert '"r3"' in outcome.text and '"r4"' in outcome.text and '"r0"' not in outcome.text


def test_one_action_is_inspected_with_its_name_after_the_options_end():
    assert _argv("inspect_workflow", workflow="wf", action="--help") == [
        "inspect",
        "--workflow=wf",
        "--sandbox",
        "action",
        "--",
        "--help",
    ]
    assert _argv("inspect_workflow", workflow="wf", action="a", view="context")[-3:] == [
        "context",
        "--",
        "a",
    ]


def test_a_view_outside_its_choices_is_refused():
    with pytest.raises(ToolRefused, match="'view' must be one of action, context"):
        check_arguments(TOOLS["inspect_workflow"], {"workflow": "wf", "view": "--fresh"})


def test_one_record_is_followed_through_the_dispositions():
    assert _argv("dispositions", workflow="wf", record="g1") == [
        "dispositions",
        "--workflow=wf",
        "--sandbox",
        "--record=g1",
        "--json",
    ]


def test_records_are_paged_with_offset(ran, tmp_path):
    _, answer = ran
    answer["done"] = _Done(stdout=json.dumps([{"n": n} for n in range(5)]))
    context = Context(project_root=tmp_path)

    page = call_tool(TOOLS["records"], {"workflow": "wf", "limit": 2, "offset": 2}, context)
    past = call_tool(TOOLS["records"], {"workflow": "wf", "offset": 9}, context)

    assert "5 records in all; records 3 to 4 are shown" in page.text
    assert '"n": 2' in page.text and '"n": 4' not in page.text
    assert "none: 'offset' 9 is past the end" in past.text


def test_each_tool_says_whether_it_changes_or_reaches_outside_anything():
    hints = {name: tool.schema()["annotations"] for name, tool in TOOLS.items()}

    assert hints["records"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert hints["run_workflow"]["destructiveHint"] and hints["run_workflow"]["openWorldHint"]
    assert hints["export_outputs"]["destructiveHint"]
    assert not hints["retry_workflow"]["destructiveHint"]
    assert all(hint["idempotentHint"] == hint["readOnlyHint"] for hint in hints.values())
