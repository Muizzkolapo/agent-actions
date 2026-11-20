"""The built-in `route` and `pick` tools, configured by an action's `_builtin` key.

`route` writes the case of each record: the value of its `on` field when that value is
a case, else `default`. Each branch's first action reads it in a guard that sends the
other records elsewhere, and `pick` joins the branches: it writes the output of the one
branch the record went through. No UDF is written for either, and a project tool of the
same name is not called in their place. The router's progress line counts each case.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

FIXTURE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "tool_action"
KINDS = ["a", "a", "b", "b", "b", "c"]

BRANCH_TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def answer_a(data: Any, *args) -> dict:
    return {"answer_a": data["source"]["page_content"]}


@udf_tool
def answer_b(data: Any, *args) -> dict:
    return {"answer_b": data["source"]["page_content"]}


@udf_tool
def answer_other(data: Any, *args) -> dict:
    return {"answer_other": data["source"]["page_content"]}


@udf_tool
def route(data: Any, *args) -> dict:
    raise RuntimeError("the project's own route tool was called")
"""


def _branch(name, impl, case):
    return f"""  - name: {name}
    kind: tool
    impl: {impl}
    intent: "Answer"
    dependencies: [router]
    schema: {{ {impl}: string }}
    context_scope: {{ observe: [source.page_content, router.case] }}
    guard: {{ condition: 'router.case == "{case}"', on_false: "filter" }}
    _sends_elsewhere: true
"""


def _config(default=True):
    cases = ["a", "b"] + (["default"] if default else [])
    router_guard = (
        ""
        if default
        else '    guard: { condition: \'source.kind == "a" OR source.kind == "b"\', '
        'on_false: "filter", passthrough_on_error: false }\n'
    )
    branches = [_branch("on_a", "answer_a", "a"), _branch("on_b", "answer_b", "b")]
    ends = ["on_a", "on_b"]
    if default:
        branches.append(_branch("on_other", "answer_other", "default"))
        ends.append("on_other")
    return (
        f"""name: {WORKFLOW}
description: "Route and pick"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: ollama_cloud
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: router
    kind: tool
    impl: agac.route
    intent: "Route"
    schema:
      type: object
      properties:
        case: {{ type: string, enum: {json.dumps(cases)} }}
      required: [case]
    context_scope: {{ observe: [source.kind] }}
{router_guard}    _builtin: {{ tool: route, field: source.kind, cases: [a, b], default: {str(default).lower()} }}
"""
        + "".join(branches)
        + f"""  - name: joined
    kind: tool
    impl: agac.pick
    intent: "Join"
    dependencies: {json.dumps(ends)}
    schema:
      name: joined_output
      fields: {json.dumps([{"id": f"answer_{e[3:]}", "type": "string"} for e in ends])}
      additionalProperties: true
      required_by_default: false
    context_scope: {{ observe: {json.dumps([f"{e}.*" for e in ends])} }}
    _builtin: {{ tool: pick, of: {json.dumps(ends)} }}
    _gathers: true
"""
    )


def _project(tmp_path, default=True):
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    staging = workflow / "agent_io" / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    staging.joinpath("pages.json").write_text(
        json.dumps([{"page_content": f"page {i}", "kind": k} for i, k in enumerate(KINDS)])
    )
    (root / "tools" / WORKFLOW / "branches.py").write_text(BRANCH_TOOLS)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_config(default))
    return root


def _run(root):
    result = run_agac(root, "run", "-a", WORKFLOW, "-u", "tools")
    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode == 0, output
    return output


def _rows(root, action):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend.read_target(action, path)
        ]
    finally:
        backend.close()


def _by_page(rows, action):
    return {row["content"]["source"]["page_content"]: row["content"][action] for row in rows}


@pytest.fixture
def routed(tmp_path):
    root = _project(tmp_path)
    return root, _run(root)


def test_route_writes_the_case_of_each_record_and_default_for_a_value_with_no_case(routed):
    root, _ = routed

    cases = [row["content"]["router"]["case"] for row in _rows(root, "router")]

    assert sorted(cases) == ["a", "a", "b", "b", "b", "default"]


def test_each_branch_runs_on_its_own_records_only(routed):
    root, _ = routed

    assert [len(_rows(root, a)) for a in ("on_a", "on_b", "on_other")] == [2, 3, 1]


def test_pick_writes_the_output_of_the_branch_each_record_went_through(routed):
    root, _ = routed

    assert _by_page(_rows(root, "joined"), "joined") == {
        "page 0": {"answer_a": "page 0"},
        "page 1": {"answer_a": "page 1"},
        "page 2": {"answer_b": "page 2"},
        "page 3": {"answer_b": "page 3"},
        "page 4": {"answer_b": "page 4"},
        "page 5": {"answer_other": "page 5"},
    }


def test_the_router_line_counts_each_case(routed):
    _, output = routed

    assert "router 6 records" in output, output
    assert "a 2, b 3, default 1" in output, output


def test_without_a_default_a_value_with_no_case_is_filtered_at_the_router(tmp_path):
    root = _project(tmp_path, default=False)

    _run(root)

    assert len(_rows(root, "router")) == 5
    assert [len(_rows(root, a)) for a in ("on_a", "on_b", "joined")] == [2, 3, 5]


@pytest.mark.parametrize("command", ["validate-udfs", "inspect"])
def test_the_checks_before_a_run_accept_the_built_in_tools(tmp_path, command):
    """`agac.route` and `agac.pick` name no UDF of the project, and no check asks for one."""
    root = _project(tmp_path)

    result = run_agac(root, command, "-a", WORKFLOW, "-u", "tools")

    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode == 0, output
    assert "not found" not in output, output
