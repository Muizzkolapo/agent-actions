"""A FILE tool that drops a record beside another branch leaves no fan-in record half empty.

A FILE tool that only drops a record gave it a `tool_missing_record` tombstone, so a
fan-in below paired it and left it unprocessed. When the same tool also split another
record, writing more rows than it was handed, the dropped record got no tombstone and
no disposition, and the fan-in ran it with the tool branch's fields None, exit 0. An
aggregate row (`source_index: None`) belongs to no source, so it joined with the other
branch's fields None in the same way (#1517).

Every command is a real `agac run` or `agac retry`. The left branch is a record tool
online and a model action in a batch; the right branch is the FILE tool.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "drop_beside"

TOOLS = """import os
from typing import Any

from agent_actions import FileUDFResult, udf_tool
from agent_actions.config.schema import Granularity


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
def pick_item(data: Any, *args) -> list[dict]:
    return [{"item_id": str(_find(data, "item_id"))}]


@udf_tool
def tag_left(data: Any, *args) -> list[dict]:
    return [{"left_tag": "L-" + str(_find(data, "item_id"))}]


def _rows(data: list[dict], *, split_a: bool, total: bool) -> FileUDFResult:
    outputs = []
    for position, record in enumerate(data):
        item = record["item_id"]
        if item == "a" and split_a:
            outputs += [
                {"source_index": position, "data": {"right_tag": f"R-a-{n}"}} for n in (1, 2, 3)
            ]
        elif item == "c" and not os.environ.get("KEEP_C"):
            continue
        else:
            outputs.append({"source_index": position, "data": {"right_tag": f"R-{item}"}})
    if total:
        outputs.append({"source_index": None, "data": {"right_tag": "total"}})
    return FileUDFResult(outputs=outputs)


@udf_tool(granularity=Granularity.FILE)
def drop_c(data: list[dict], **kwargs) -> FileUDFResult:
    return _rows(data, split_a=False, total=False)


@udf_tool(granularity=Granularity.FILE)
def split_a_drop_c(data: list[dict], **kwargs) -> FileUDFResult:
    return _rows(data, split_a=True, total=False)


@udf_tool(granularity=Granularity.FILE)
def drop_c_with_total(data: list[dict], **kwargs) -> FileUDFResult:
    return _rows(data, split_a=False, total=True)


@udf_tool
def tag_from_right(data: Any, *args) -> list[dict]:
    return [{"left_tag": "L-" + str(_find(data, "right_tag"))}]


@udf_tool
def shout_right(data: Any, *args) -> list[dict]:
    return [{"right_tag": str(_find(data, "right_tag")).upper()}]


@udf_tool
def join_tags(data: Any, *args) -> list[dict]:
    left = _find(data, "left_tag")
    side = "None" if left is None else str(left) if str(left).startswith("L-") else "L"
    return [{"joined": f"{side}|{_find(data, 'right_tag')}"}]
"""

PROMPTS = """{prompt Left}
Tag this item.
{{ stage.item_id }}
```json
{"left_tag": "..."}
```
{end_prompt}
"""


def _config(right_impl: str, *, batch: bool, shape: str = "beside") -> str:
    """*shape*: `beside` puts `left` beside `right`; `below` adds a record action under
    `right` that the fan-in reads; `under` has `left` read `right`, so every branch of the
    fan-in is below the FILE tool."""
    left = (
        "  - name: left\n"
        '    intent: "left branch"\n'
        "    schema: left_out\n"
        f"    prompt: ${WORKFLOW}.Left\n"
        "    dependencies: [stage]\n"
        "    context_scope: { observe: [stage.item_id] }\n"
        if batch
        else "  - name: left\n"
        "    kind: tool\n"
        '    intent: "left branch"\n'
        "    impl: tag_left\n"
        "    schema: left_out\n"
        "    dependencies: [stage]\n"
        "    context_scope: { observe: [stage.item_id] }\n"
    )
    if shape == "under":
        left = (
            "  - name: left\n"
            "    kind: tool\n"
            '    intent: "left branch, below the FILE tool"\n'
            "    impl: tag_from_right\n"
            "    schema: left_out\n"
            "    dependencies: [right]\n"
            "    context_scope: { observe: [right.right_tag] }\n"
        )
    below = (
        "  - name: loud\n"
        "    kind: tool\n"
        '    intent: "one record per record of the FILE tool"\n'
        "    impl: shout_right\n"
        "    schema: right_out\n"
        "    dependencies: [right]\n"
        "    context_scope: { observe: [right.right_tag] }\n"
        if shape == "below"
        else ""
    )
    read = "loud" if shape == "below" else "right"
    return (
        f"name: {WORKFLOW}\n"
        'description: "fan-in beside a FILE tool that drops a record"\n'
        'version: "0.1.0"\n'
        "defaults:\n"
        "  json_mode: true\n"
        "  granularity: Record\n"
        f"  run_mode: {'batch' if batch else 'online'}\n"
        "  model_vendor: agac-provider\n"
        "  model_name: mock\n"
        "  api_key: OLLAMA_API_KEY\n"
        "  data_source: { type: local, folder: ./staging, file_type: [json] }\n"
        "actions:\n"
        "  - name: stage\n"
        "    kind: tool\n"
        '    intent: "the item"\n'
        "    impl: pick_item\n"
        "    schema: stage_out\n"
        "    context_scope: { observe: [source.item_id] }\n" + left + "  - name: right\n"
        "    kind: tool\n"
        '    intent: "a FILE tool"\n'
        f"    impl: {right_impl}\n"
        "    granularity: File\n"
        "    schema: right_out\n"
        "    dependencies: [stage]\n"
        "    context_scope: { observe: [stage.item_id] }\n" + below + "  - name: join\n"
        "    kind: tool\n"
        '    intent: "fan-in"\n'
        "    impl: join_tags\n"
        "    schema: join_out\n"
        f"    dependencies: [left, {read}]\n"
        f"    context_scope: {{ observe: [left.left_tag, {read}.right_tag] }}\n"
    )


def _project(root: Path, right_impl: str, *, batch: bool = False, shape: str = "beside") -> Path:
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
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _config(right_impl, batch=batch, shape=shape)
    )
    (workflow / "agent_io" / "staging" / "items.json").write_text(
        json.dumps([{"item_id": "a"}, {"item_id": "b"}, {"item_id": "c"}])
    )
    (root / "tools" / WORKFLOW / "drop_beside_tools.py").write_text(TOOLS)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(PROMPTS)
    for action, field in (
        ("stage", "item_id"),
        ("left", "left_tag"),
        ("right", "right_tag"),
        ("join", "joined"),
    ):
        (root / "schema" / WORKFLOW / f"{action}_out.yml").write_text(
            f"name: {action}_out\nfields:\n  - id: {field}\n    type: string\n"
        )
    return root


def _db(root: Path) -> Path:
    return root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.db"


def _stored(root: Path, action: str) -> list[dict]:
    with sqlite3.connect(_db(root)) as conn:
        found = conn.execute(
            "select data from target_data where action_name = ?", (action,)
        ).fetchall()
    return [record for (data,) in found for record in json.loads(data)]


def _joined(root: Path) -> list[str]:
    return sorted(
        row["content"]["join"]["joined"]
        for row in _stored(root, "join")
        if (row.get("content") or {}).get("join")
    )


def _dispositions(root: Path, action: str) -> dict[str, tuple[str, str | None]]:
    with sqlite3.connect(_db(root)) as conn:
        found = conn.execute(
            "select record_id, disposition, reason from record_disposition where action_name = ?",
            (action,),
        ).fetchall()
    return {record_id: (disposition, reason) for record_id, disposition, reason in found}


def _source_of(root: Path, item: str) -> str:
    return next(
        row["source_guid"]
        for row in _stored(root, "stage")
        if row["content"]["stage"]["item_id"] == item
    )


def _run(root: Path, *args: str, env: dict[str, str] | None = None):
    return run_agac(
        root,
        "run",
        "-a",
        WORKFLOW,
        *args,
        env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0", **(env or {})},
    )


def _settle(root: Path, env: dict[str, str] | None = None):
    """Run, then run again until a batch run has collected every batch it submitted."""
    result = _run(root, "--fresh", env=env)
    for _ in range(3):
        if "run again to continue" not in result.stdout + result.stderr:
            break
        result = _run(root, env=env)
    return result


ONLINE_SPLIT = ["L-a|R-a-1", "L-a|R-a-2", "L-a|R-a-3", "L-b|R-b"]
BATCH_SPLIT = ["L|R-a-1", "L|R-a-2", "L|R-a-3", "L|R-b"]
DROPPED = ("unprocessed", "tool_missing_record")


def test_a_tool_that_only_drops_a_record_leaves_it_unprocessed(tmp_path):
    """What already holds, and what the splitting tool below must match."""
    root = _project(tmp_path, "drop_c")

    result = _run(root, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _joined(root) == ["L-a|R-a", "L-b|R-b"]
    assert _dispositions(root, "right")[_source_of(root, "c")] == DROPPED


@pytest.mark.parametrize("batch", [False, True], ids=["online", "batch"])
def test_a_tool_that_splits_one_record_and_drops_another_leaves_it_unprocessed(tmp_path, batch):
    root = _project(tmp_path, "split_a_drop_c", batch=batch)

    result = _settle(root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _joined(root) == (BATCH_SPLIT if batch else ONLINE_SPLIT)
    dropped = _source_of(root, "c")
    assert _dispositions(root, "right").get(dropped) == DROPPED
    assert _dispositions(root, "join").get(dropped, ("",))[0] == "unprocessed"


@pytest.mark.parametrize("command", ["retry", "run"])
def test_a_later_command_leaves_the_dropped_record_as_the_drop_only_tool_does(tmp_path, command):
    """`agac retry` finds nothing failed and `agac run` finds the workflow complete, for
    the tool that only drops as for the one that splits too; neither runs it half empty."""
    root = _project(tmp_path, "split_a_drop_c")
    _run(root, "--fresh")

    result = run_agac(root, command, "-a", WORKFLOW)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _joined(root) == ONLINE_SPLIT
    assert _dispositions(root, "right").get(_source_of(root, "c")) == DROPPED


@pytest.mark.parametrize("batch", [False, True], ids=["online", "batch"])
@pytest.mark.parametrize("keep_c", [False, True], ids=["one_dropped", "every_one_named"])
def test_an_aggregate_row_beside_another_branch_fails_the_fan_in(tmp_path, batch, keep_c):
    """The aggregate belongs to no source, so no record of the other branch is its partner."""
    root = _project(tmp_path, "drop_c_with_total", batch=batch)

    result = _settle(root, env={"KEEP_C": "1"} if keep_c else None)

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "join" in output and "right" in output
    assert "source_index" in output
    assert _joined(root) == []


def test_an_aggregate_carried_below_the_tool_still_fails_the_fan_in(tmp_path):
    root = _project(tmp_path, "drop_c_with_total", shape="below")

    result = _run(root, "--fresh")

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "right" in output and "source_index" in output
    assert _joined(root) == []


def test_an_aggregate_every_branch_reads_pairs_like_any_record(tmp_path):
    root = _project(tmp_path, "drop_c_with_total", shape="under")

    result = _run(root, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _joined(root) == ["L-R-a|R-a", "L-R-b|R-b", "L-total|total"]
