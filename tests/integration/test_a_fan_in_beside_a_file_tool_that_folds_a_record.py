"""A FILE tool that folds one record into another's row leaves the folded one unprocessed
at a fan-in beside another branch, rather than running it half empty.

The tool returns one row with `source_index: [a, b]`: `b` has no row of its own in that
branch. Beside another branch, the fan-in ran `b` with the folding branch's fields None
and exited 0 (#1523). `b` is now left `unprocessed` at the fan-in, with the reason
`consumed_into_another_record`, and its tombstone names the record it went into.

Every command is a real `agac run`, `agac retry` or `agac dispositions`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

WORKFLOW = "fold_beside"
CONSUMED = ("unprocessed", "consumed_into_another_record")

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
def fold_pick_item(data: Any, *args) -> list[dict]:
    return [{"item_id": str(_find(data, "item_id"))}]


@udf_tool
def fold_tag_left(data: Any, *args) -> list[dict]:
    return [{"left_tag": "L-" + str(_find(data, "item_id"))}]


@udf_tool(granularity=Granularity.FILE)
def fold_b_into_a(data: list[dict], **kwargs) -> FileUDFResult:
    at = {record["item_id"]: position for position, record in enumerate(data)}
    outputs = []
    if "a" in at and "b" in at:
        outputs.append({"source_index": [at["a"], at["b"]], "data": {"right_tag": "R-ab"}})
    else:
        outputs += [
            {"source_index": at[item], "data": {"right_tag": f"R-{item}"}}
            for item in ("a", "b")
            if item in at
        ]
    if "c" in at:
        outputs.append({"source_index": at["c"], "data": {"right_tag": "R-c"}})
    return FileUDFResult(outputs=outputs)


@udf_tool
def fold_shout_right(data: Any, *args) -> list[dict]:
    return [{"right_tag": str(_find(data, "right_tag")).upper()}]


@udf_tool
def fold_join_tags(data: Any, *args) -> list[dict]:
    left = _find(data, "left_tag")
    side = "None" if left is None else str(left) if str(left).startswith("L-") else "L"
    return [{"joined": f"{side}|{_find(data, 'right_tag')}"}]


@udf_tool(granularity=Granularity.FILE)
def fold_join_file(data: list[dict], **kwargs) -> list:
    for item in data:
        joined = f"{item.get('left_tag')}|{item.get('right_tag')}"
        item.clear()
        item["joined"] = joined
    return data
"""

PROMPTS = """{prompt Left}
Tag this item.
{{ stage.item_id }}
```json
{"left_tag": "..."}
```
{end_prompt}

{prompt Join}
Join these tags.
{{ left.left_tag }} {{ right.right_tag }}
```json
{"joined": "..."}
```
{end_prompt}
"""


def _config(*, run_mode: str, left_llm: bool, join: str, shape: str) -> str:
    """*shape*: `beside` puts `left` beside the FILE tool `right`; `below` has the fan-in
    read `loud`, a record tool under `right`; `alone` has no fan-in, only `loud`."""
    left = (
        "  - name: left\n"
        '    intent: "left branch"\n'
        "    schema: left_out\n"
        f"    prompt: ${WORKFLOW}.Left\n"
        "    dependencies: [stage]\n"
        "    context_scope: { observe: [stage.item_id] }\n"
        if left_llm
        else "  - name: left\n"
        "    kind: tool\n"
        '    intent: "left branch"\n'
        "    impl: fold_tag_left\n"
        "    schema: left_out\n"
        "    dependencies: [stage]\n"
        "    context_scope: { observe: [stage.item_id] }\n"
    )
    loud = (
        "  - name: loud\n"
        "    kind: tool\n"
        '    intent: "one record per record of the FILE tool"\n'
        "    impl: fold_shout_right\n"
        "    schema: right_out\n"
        "    dependencies: [right]\n"
        "    context_scope: { observe: [right.right_tag] }\n"
    )
    read = "loud" if shape == "below" else "right"
    join_body = {
        "llm": f"    schema: join_out\n    prompt: ${WORKFLOW}.Join\n",
        "tool": "    kind: tool\n    impl: fold_join_tags\n    schema: join_out\n",
        "file": "    kind: tool\n    impl: fold_join_file\n    granularity: File\n"
        "    schema: join_out\n",
    }[join]
    fan_in = (
        "  - name: join\n"
        '    intent: "fan-in"\n' + join_body + f"    dependencies: [left, {read}]\n"
        f"    context_scope: {{ observe: [left.left_tag, {read}.right_tag] }}\n"
    )
    tail = loud if shape == "alone" else left + (loud if shape == "below" else "") + fan_in
    return (
        f"name: {WORKFLOW}\n"
        'description: "fan-in beside a FILE tool that folds a record"\n'
        'version: "0.1.0"\n'
        "defaults:\n"
        "  json_mode: true\n"
        "  granularity: Record\n"
        f"  run_mode: {run_mode}\n"
        "  model_vendor: agac-provider\n"
        "  model_name: mock\n"
        "  api_key: OLLAMA_API_KEY\n"
        "  data_source: { type: local, folder: ./staging, file_type: [json] }\n"
        "actions:\n"
        "  - name: stage\n"
        "    kind: tool\n"
        '    intent: "the item"\n'
        "    impl: fold_pick_item\n"
        "    schema: stage_out\n"
        "    context_scope: { observe: [source.item_id] }\n"
        "  - name: right\n"
        "    kind: tool\n"
        '    intent: "a FILE tool that folds b into a"\n'
        "    impl: fold_b_into_a\n"
        "    granularity: File\n"
        "    schema: right_out\n"
        "    dependencies: [stage]\n"
        "    context_scope: { observe: [stage.item_id] }\n" + tail
    )


def _project(
    root: Path,
    *,
    batch: bool = False,
    left_llm: bool | None = None,
    join: str = "tool",
    shape: str = "beside",
) -> Path:
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
        _config(
            run_mode="batch" if batch else "online",
            left_llm=batch if left_llm is None else left_llm,
            join=join,
            shape=shape,
        )
    )
    (workflow / "agent_io" / "staging" / "items.json").write_text(
        json.dumps([{"item_id": "a"}, {"item_id": "b"}, {"item_id": "c"}])
    )
    (root / "tools" / WORKFLOW / "fold_beside_tools.py").write_text(TOOLS)
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
    found = stored_rows(_db(root), "select data from target_data where action_name = ?", action)
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


def _run(root: Path, *args: str):
    return run_agac(
        root, "run", "-a", WORKFLOW, *args, env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}
    )


def _settle(root: Path):
    """Run, then run again until a batch run has collected every batch it submitted."""
    result = _run(root, "--fresh")
    for _ in range(3):
        if "run again to continue" not in result.stdout + result.stderr:
            break
        result = _run(root)
    return result


def _assert_b_left_unprocessed(root: Path) -> None:
    a, b = _source_of(root, "a"), _source_of(root, "b")
    assert _dispositions(root, "right").get(b) == ("success", "consumed_into_output")
    assert _dispositions(root, "join").get(b) == CONSUMED
    rows = [row for row in _stored(root, "join") if row.get("source_guid") == b]
    assert [row["content"].get("join") for row in rows] == [None]
    assert rows[0]["metadata"]["reason"] == "consumed_into_another_record"
    assert rows[0]["metadata"]["consumed_into"] == a


@pytest.mark.parametrize("batch", [False, True], ids=["online", "batch"])
def test_the_folded_record_is_left_unprocessed_at_the_fan_in(tmp_path, batch):
    root = _project(tmp_path, batch=batch)

    result = _settle(root)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert _joined(root) == (["L-a|R-ab", "L-c|R-c"] if not batch else ["L|R-ab", "L|R-c"])
    _assert_b_left_unprocessed(root)
    assert "consumed into another record" in output


def test_a_folded_record_carried_below_the_tool_is_left_unprocessed(tmp_path):
    root = _project(tmp_path, shape="below")

    result = _run(root, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _joined(root) == ["L-a|R-AB", "L-c|R-C"]
    _assert_b_left_unprocessed(root)


@pytest.mark.parametrize("batch", [False, True], ids=["online", "batch"])
def test_a_model_action_at_the_fan_in_leaves_it_unprocessed_too(tmp_path, batch):
    root = _project(tmp_path, batch=batch, left_llm=False, join="llm")

    result = _settle(root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_joined(root)) == 2
    _assert_b_left_unprocessed(root)


def test_a_file_tool_at_the_fan_in_leaves_it_unprocessed_too(tmp_path):
    root = _project(tmp_path, join="file")

    result = _run(root, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _joined(root) == ["L-a|R-ab", "L-c|R-c"]
    _assert_b_left_unprocessed(root)


@pytest.mark.parametrize("command", ["retry", "run"])
def test_a_later_command_leaves_the_folded_record_unprocessed(tmp_path, command):
    root = _project(tmp_path)
    _run(root, "--fresh")

    result = run_agac(root, command, "-a", WORKFLOW)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _joined(root) == ["L-a|R-ab", "L-c|R-c"]
    _assert_b_left_unprocessed(root)


def test_agac_preview_and_dispositions_show_the_folded_record_unprocessed(tmp_path):
    root = _project(tmp_path)
    _run(root, "--fresh")
    a = _source_of(root, "a")

    preview = run_agac(root, "preview", "-w", WORKFLOW, "-a", "join", "-f", "json")
    summary = run_agac(root, "dispositions", "-a", WORKFLOW, "--action", "join")

    assert preview.returncode == 0, preview.stdout + preview.stderr
    shown = preview.stdout.replace(" ", "").replace("\n", "")
    assert '"reason":"consumed_into_another_record"' in shown
    assert f'"consumed_into":"{a}"' in shown
    assert summary.returncode == 0, summary.stdout + summary.stderr
    join_row = next(line for line in summary.stdout.splitlines() if "join" in line)
    assert [cell.strip() for cell in join_row.strip("│ ").split("│")][1:5] == ["2", "0", "0", "1"]


def test_folding_with_no_fan_in_below_carries_the_folded_row_alone(tmp_path):
    root = _project(tmp_path, shape="alone")

    result = _run(root, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    a, b, c = (_source_of(root, item) for item in "abc")
    assert sorted(
        (row["source_guid"], row["content"]["loud"]["right_tag"]) for row in _stored(root, "loud")
    ) == sorted([(a, "R-AB"), (c, "R-C")])
    assert _dispositions(root, "right").get(b) == ("success", "consumed_into_output")
    assert b not in _dispositions(root, "loud")
    again = _run(root)
    assert again.returncode == 0, again.stdout + again.stderr
    assert len(_stored(root, "loud")) == 2
