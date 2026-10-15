"""A fan-in's dependencies are all inputs: their order changes nothing.

The docs and `agac inspect action` said the first dependency drives the execution
count and the others are context. A run reads every dependency's records and merges
them by source record, whatever the order.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from agent_actions.prompt.context.scope_inference import infer_dependencies
from tests._support.agac_cli import run_agac

WORKFLOW = "fanin_probe"

TOOLS = """from typing import Any

from agent_actions import udf_tool


def _find(d: Any, key: str):
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            hit = _find(v, key)
            if hit is not None:
                return hit
    return None


@udf_tool
def tag_left(data: Any, *args) -> list[dict]:
    return [{"left_tag": "L-" + str(_find(data, "item_id"))}]


@udf_tool
def tag_right(data: Any, *args) -> list[dict]:
    return [{"right_tag": "R-" + str(_find(data, "item_id"))}]


@udf_tool
def join_tags(data: Any, *args) -> list[dict]:
    return [{"joined": f"{_find(data, 'left_tag')}|{_find(data, 'right_tag')}"}]
"""


def _config(dependencies: str) -> str:
    return f"""name: {WORKFLOW}
description: "fan-in of two branches with different record counts"
version: "0.1.0"
defaults:
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: left
    kind: tool
    intent: "every record"
    impl: tag_left
    schema: left_out
    context_scope: {{ observe: [source.item_id] }}
  - name: right
    kind: tool
    intent: "only the record kept"
    impl: tag_right
    schema: right_out
    guard: {{ condition: 'source.keep == true', on_false: filter }}
    context_scope: {{ observe: [source.item_id, source.keep] }}
  - name: join
    kind: tool
    intent: "fan-in"
    impl: join_tags
    schema: join_out
    dependencies: [{dependencies}]
    context_scope: {{ observe: [left.left_tag, right.right_tag] }}
"""


def _project(root: Path, dependencies: str) -> Path:
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "agent_actions.yml").write_text(
        "default_agent_config:\n  api_key: OLLAMA_API_KEY\n  model_name: gpt-oss:120b-cloud\n"
        'tool_path: ["tools"]\nschema_path: schema\n'
    )
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_config(dependencies))
    (workflow / "agent_io" / "staging" / "items.json").write_text(
        json.dumps(
            [
                {"item_id": "a", "keep": True},
                {"item_id": "b", "keep": False},
                {"item_id": "c", "keep": False},
            ]
        )
    )
    (root / "tools" / WORKFLOW / "probe_tools.py").write_text(TOOLS)
    for action, field in (("left", "left_tag"), ("right", "right_tag"), ("join", "joined")):
        (root / "schema" / WORKFLOW / f"{action}_out.yml").write_text(
            f"name: {action}_out\nfields:\n  - id: {field}\n    type: string\n"
        )
    return root


def _rows(root: Path, action: str) -> list[dict]:
    db = root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.db"
    with sqlite3.connect(db) as conn:
        found = conn.execute(
            "select data from target_data where action_name = ?", (action,)
        ).fetchall()
    return [record["content"][action] for (data,) in found for record in json.loads(data)]


@pytest.mark.parametrize("dependencies", ["left, right", "right, left"])
def test_the_order_of_dependencies_does_not_change_what_a_fan_in_runs_on(tmp_path, dependencies):
    root = _project(tmp_path, dependencies)

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_rows(root, "left")) == 3
    assert len(_rows(root, "right")) == 1
    assert _rows(root, "join") == [{"joined": "L-a|R-a"}]


@pytest.mark.parametrize(
    ("dependencies", "listed"),
    [("left, right", "left, right"), ("right, left", "right, left")],
)
def test_inspect_lists_every_dependency_of_a_fan_in_as_an_input(tmp_path, dependencies, listed):
    root = _project(tmp_path, dependencies)

    result = run_agac(root, "inspect", "action", "-a", WORKFLOW, "join", env={"COLUMNS": "200"})

    assert result.returncode == 0, result.stdout + result.stderr
    input_line = next(line for line in result.stdout.splitlines() if "Input" in line)
    assert listed in input_line
    assert "merge of 2" in input_line
    assert "context" not in input_line


@pytest.mark.parametrize(
    "dependencies",
    [["left", "right"], ["right", "left"], ["research_1", "research_2", "summarize"]],
)
def test_every_dependency_is_an_input_source(dependencies):
    workflow_actions = ["left", "right", "research_1", "research_2", "summarize", "join"]
    config = {
        "dependencies": dependencies,
        "context_scope": {"observe": [f"{d}.*" for d in dependencies]},
    }

    input_sources, context_sources = infer_dependencies(config, workflow_actions, "join")

    assert input_sources == dependencies
    assert context_sources == []
