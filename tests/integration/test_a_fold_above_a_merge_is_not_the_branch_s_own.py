"""A fold made above a merge is not a fold by the branch or version that lacks the record
(1537).

A `granularity: File` tool above the merge that pairs each record with the next
(`source_index: [i, i + 1]`) lists the next record in each row's `folded_sources`, and
every record built below it keeps that list, though the next record keeps its own row.
A version that guard-filters that record then lacks it, and the version merge read the
inherited list as the version folding it: it logged the record as consumed into another
record's output. Only the version's own folds count now.

A fan-in reads the same list, but a branch never lacks such a record there: one a
guard filtered is dropped from every branch before pairing, and one a File tool leaves
out holds a tombstone. Those cases are pinned here as coverage.

Every command is a real `agac run`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "fold_above"

TOOLS = """from typing import Any

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
def fold_above_pick(data: Any, *args) -> list[dict]:
    return [{"item_id": str(_find(data, "item_id"))}]


@udf_tool(granularity=Granularity.FILE)
def fold_above_pair(data: list[dict], **kwargs) -> FileUDFResult:
    n = len(data)
    return FileUDFResult(
        outputs=[
            {
                "source_index": [i, i + 1] if i + 1 < n else i,
                "data": {"item_id": str(_find(data[i], "item_id"))},
            }
            for i in range(n)
        ]
    )


@udf_tool
def fold_above_tag(data: Any, *args) -> list[dict]:
    return [{"tag": str(_find(data, "item_id"))}]


@udf_tool(granularity=Granularity.FILE)
def fold_above_leave_out_b(data: list[dict], **kwargs) -> FileUDFResult:
    return FileUDFResult(
        outputs=[
            {"source_index": i, "data": {"tag": str(_find(r, "item_id"))}}
            for i, r in enumerate(data)
            if str(_find(r, "item_id")) != "b"
        ]
    )


@udf_tool
def fold_above_join(data: Any, *args) -> list[dict]:
    return [{"tags": "|".join(str(_find(v, "tag")) for k, v in sorted(data.items()) if v)}]
"""

HEAD = f"""name: {WORKFLOW}
description: "a fold above a merge"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: stage
    kind: tool
    intent: "the item"
    impl: fold_above_pick
    schema: stage_out
    context_scope: {{ observe: [source.item_id] }}
  - name: paired
    kind: tool
    intent: "pair each item with the next"
    impl: fold_above_pair
    granularity: File
    schema: stage_out
    dependencies: [stage]
    context_scope: {{ observe: [stage.item_id] }}
"""

VERSIONS = """  - name: check
    kind: tool
    intent: "tag; version 2 filters b"
    impl: fold_above_tag
    versions: { param: pass_no, range: [1, 2] }
    schema: tag_out
    dependencies: [paired]
    guard: { condition: "paired.item_id != 'b' or version.pass_no == 1", on_false: filter }
    context_scope: { observe: [paired.item_id] }
  - name: merged
    kind: tool
    intent: "merge the versions"
    impl: fold_above_join
    schema: join_out
    dependencies: [check]
    version_consumption: { source: check, pattern: merge }
    context_scope: { observe: [check_1.tag, check_2.tag] }
"""

BRANCHES = """  - name: left
    kind: tool
    intent: "tag; filters b"
    impl: fold_above_tag
    schema: tag_out
    dependencies: [paired]
    guard: { condition: "paired.item_id != 'b'", on_false: filter }
    context_scope: { observe: [paired.item_id] }
  - name: right
    kind: tool
    intent: "tag"
    impl: fold_above_tag
    schema: tag_out
    dependencies: [paired]
    context_scope: { observe: [paired.item_id] }
  - name: merged
    kind: tool
    intent: "fan-in"
    impl: fold_above_join
    schema: join_out
    dependencies: [left, right]
    context_scope: { observe: [left.tag, right.tag] }
"""


LEFT_FILE = BRANCHES.replace(
    """    impl: fold_above_tag
    schema: tag_out
    dependencies: [paired]
    guard: { condition: "paired.item_id != 'b'", on_false: filter }
""",
    """    impl: fold_above_leave_out_b
    granularity: File
    schema: tag_out
    dependencies: [paired]
""",
)


def _project(root: Path, tail: str) -> Path:
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        "default_agent_config:\n  api_key: OLLAMA_API_KEY\n  model_name: mock\n"
        'tool_path: ["tools"]\nschema_path: schema\n'
    )
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(HEAD + tail)
    (workflow / "agent_io" / "staging" / "items.json").write_text(
        json.dumps([{"item_id": "a"}, {"item_id": "b"}, {"item_id": "c"}])
    )
    (root / "tools" / WORKFLOW / "fold_above_tools.py").write_text(TOOLS)
    for name, field in (("stage_out", "item_id"), ("tag_out", "tag"), ("join_out", "tags")):
        (root / "schema" / WORKFLOW / f"{name}.yml").write_text(
            f"name: {name}\nfields:\n  - id: {field}\n    type: string\n"
        )
    return root


def _db(root: Path) -> Path:
    return root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.db"


def _source_of(root: Path, item: str) -> str:
    with sqlite3.connect(_db(root)) as conn:
        rows = conn.execute("select data from target_data where action_name = 'stage'").fetchall()
    return next(
        r["source_guid"]
        for (data,) in rows
        for r in json.loads(data)
        if r["content"]["stage"]["item_id"] == item
    )


def _reasons(root: Path, action: str) -> dict[str, str | None]:
    with sqlite3.connect(_db(root)) as conn:
        rows = conn.execute(
            "select record_id, reason from record_disposition where action_name = ?", (action,)
        ).fetchall()
    return dict(rows)


@pytest.mark.parametrize(
    "tail",
    [VERSIONS, BRANCHES, LEFT_FILE],
    ids=["version-merge-guard", "fan-in-guard", "fan-in-file-tool-leaves-it-out"],
)
def test_a_record_a_branch_lacks_below_a_fold_is_not_called_consumed(tmp_path, tail):
    root = _project(tmp_path, tail)

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    b = _source_of(root, "b")
    assert _reasons(root, "merged").get(b) != "consumed_into_another_record", output
    assert "consumed into another record" not in output, output
    assert "consumed_into_another_record" not in output, output
