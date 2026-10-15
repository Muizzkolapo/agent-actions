"""A fan-in over a branch that split its records pairs each one with the other branch.

A branch that returns several records per input gives each a new source id, so the
merge grouped every record alone: the fan-in ran once per record of each branch with
the other branch's fields empty, and the run reported success (#1430).
"""

import json
import sqlite3
from pathlib import Path

import pytest

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
def split_left(data: Any, *args) -> list[dict]:
    item = str(_find(data, "item_id"))
    return [{"left_tag": f"L-{item}-1"}, {"left_tag": f"L-{item}-2"}]


@udf_tool
def split_right(data: Any, *args) -> list[dict]:
    item = str(_find(data, "item_id"))
    return [{"right_tag": f"R-{item}-1"}, {"right_tag": f"R-{item}-2"}]


@udf_tool
def shout_right(data: Any, *args) -> list[dict]:
    return [{"loud_tag": str(_find(data, "right_tag")).upper()}]


@udf_tool
def join_tags(data: Any, *args) -> list[dict]:
    right = _find(data, "loud_tag") or _find(data, "right_tag")
    return [{"joined": f"{_find(data, 'left_tag')}|{right}"}]
"""

LEFT = """  - name: left
    kind: tool
    intent: "left branch"
    impl: {impl}
    schema: left_out
    context_scope: {{ observe: [source.item_id] }}
"""

RIGHT = """  - name: right
    kind: tool
    intent: "two records per input"
    impl: split_right
    schema: right_out
    context_scope: { observe: [source.item_id] }
"""

LOUD = """  - name: loud
    kind: tool
    intent: "one record per input, after the split"
    impl: shout_right
    schema: loud_out
    dependencies: [right]
    context_scope: { observe: [right.right_tag] }
"""


def _config(dependencies: str, *, left_impl: str = "tag_left", after_split: bool = False) -> str:
    branch = "loud" if after_split else "right"
    field = "loud.loud_tag" if after_split else "right.right_tag"
    return (
        f"name: {WORKFLOW}\n"
        'description: "fan-in over a branch that splits each record in two"\n'
        'version: "0.1.0"\n'
        "defaults:\n"
        "  granularity: Record\n"
        "  run_mode: online\n"
        "  model_vendor: agac-provider\n"
        "  model_name: mock\n"
        "  api_key: OLLAMA_API_KEY\n"
        "  data_source: { type: local, folder: ./staging, file_type: [json] }\n"
        "actions:\n"
        + LEFT.format(impl=left_impl)
        + RIGHT
        + (LOUD if after_split else "")
        + "  - name: join\n"
        "    kind: tool\n"
        '    intent: "fan-in"\n'
        "    impl: join_tags\n"
        "    schema: join_out\n"
        f"    dependencies: [{dependencies.replace('right', branch)}]\n"
        f"    context_scope: {{ observe: [left.left_tag, {field}] }}\n"
    )


def _project(root: Path, config: str) -> Path:
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
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(config)
    (workflow / "agent_io" / "staging" / "items.json").write_text(
        json.dumps([{"item_id": "a"}, {"item_id": "b"}, {"item_id": "c"}])
    )
    (root / "tools" / WORKFLOW / "probe_tools.py").write_text(TOOLS)
    for action, field in (
        ("left", "left_tag"),
        ("right", "right_tag"),
        ("loud", "loud_tag"),
        ("join", "joined"),
    ):
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


def _joined(root: Path) -> list[str]:
    return sorted(row["joined"] for row in _rows(root, "join"))


PAIRED = sorted(f"L-{item}|R-{item}-{n}" for item in ("a", "b", "c") for n in (1, 2))


@pytest.mark.parametrize("dependencies", ["left, right", "right, left"])
def test_no_fan_in_record_is_missing_a_branch(tmp_path, dependencies):
    root = _project(tmp_path, _config(dependencies))

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_rows(root, "left")) == 3
    assert len(_rows(root, "right")) == 6
    assert not [joined for joined in _joined(root) if "None" in joined]


@pytest.mark.parametrize("dependencies", ["left, right", "right, left"])
def test_each_split_record_is_paired_with_the_record_it_came_from(tmp_path, dependencies):
    root = _project(tmp_path, _config(dependencies))

    run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert _joined(root) == PAIRED


def test_a_split_branch_read_through_a_later_action_is_paired_too(tmp_path):
    root = _project(tmp_path, _config("left, right", after_split=True))

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _joined(root) == sorted(
        f"L-{item}|R-{item.upper()}-{n}" for item in ("a", "b", "c") for n in (1, 2)
    )


def test_two_branches_split_from_one_record_fail_the_fan_in(tmp_path):
    root = _project(tmp_path, _config("left, right", left_impl="split_left"))

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "join" in output
    assert "left" in output and "right" in output
    assert "None" not in " ".join(_joined(root))
