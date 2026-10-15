"""A fan-in over a branch that returns several records per input pairs each with its source.

`right` splits every staged page into two records; `left` returns one. `join` ran once
per record of either branch, each run seeing only its own branch, and exited 0.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "tool_action"
PAGES = ["a", "b", "c"]

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def fanin_left(data: Any, *args) -> list[dict]:
    return [{"summary": f"L-{data['source']['page_content']}", "exam_density": "low"}]


@udf_tool
def fanin_right(data: Any, *args) -> list[dict]:
    page = data["source"]["page_content"]
    return [{"summary": f"R-{page}-1", "exam_density": "low"}, {"summary": f"R-{page}-2", "exam_density": "low"}]


@udf_tool
def fanin_join(data: Any, *args) -> list[dict]:
    return [{"summary": f"{data['left']['summary']}|{data['right']['summary']}", "exam_density": "low"}]
"""


def _action(name, impl, dependencies, observe):
    return (
        f"  - name: {name}\n"
        f"    kind: tool\n"
        f"    dependencies: [{', '.join(dependencies)}]\n"
        f'    intent: "{name}"\n'
        f"    schema: tool_action_output\n"
        f"    impl: {impl}\n"
        f"    context_scope: {{ observe: [{', '.join(observe)}] }}\n"
        f"    expect: {{ repair: none }}\n"
    )


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(json.dumps([{"page_content": p} for p in PAGES]))
    (root / "tools" / WORKFLOW / "fan_in_over_a_split.py").write_text(TOOLS)
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    return root


def _workflow(project, run_mode, join_dependencies):
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    head = (
        config.read_text().split("actions:")[0].replace("run_mode: online", f"run_mode: {run_mode}")
    )
    config.write_text(
        head
        + "actions:\n"
        + _action("left", "fanin_left", [], ["source.page_content"])
        + _action("right", "fanin_right", [], ["source.page_content"])
        + _action("join", "fanin_join", join_dependencies, ["left.summary", "right.summary"])
    )


def _summaries(project, action):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        rows = [
            r for f in backend.list_target_files(action) for r in backend.read_target(action, f)
        ]
    finally:
        backend.close()
    return sorted(r["content"][action]["summary"] for r in rows)


@pytest.mark.parametrize("run_mode", ["online", "batch"])
@pytest.mark.parametrize("order", [["left", "right"], ["right", "left"]], ids=["lr", "rl"])
def test_each_split_record_is_paired_with_its_sources_other_branch(project, run_mode, order):
    _workflow(project, run_mode, order)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

    assert result.exit_code == 0, result.output
    assert _summaries(project, "right") == [f"R-{p}-{i}" for p in PAGES for i in (1, 2)]
    assert _summaries(project, "join") == [f"L-{p}|R-{p}-{i}" for p in PAGES for i in (1, 2)]
