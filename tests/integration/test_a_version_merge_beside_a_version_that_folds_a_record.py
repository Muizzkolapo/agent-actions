"""A versioned FILE tool that folds a record in one version only leaves it unprocessed
at the version merge (1537).

One version returns a row with `source_index: [a, b]`, so `b` has no row in that
version; the other version keeps `b`'s own row. The version merge correlates versions
by record, not through `merge_fan_in`, so it ran `b` with the folding version's
namespace missing, and exited 0. `b` is now left `unprocessed` at the merge with reason
`consumed_into_another_record`, its tombstone naming the row it went into, as at a
fan-in (1523).

Which version folds is whichever calls the tool first; nothing below depends on it.

Every command is a real `agac run` or `agac dispositions`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "fold_one_version"
CONSUMED = ("unprocessed", "consumed_into_another_record")

TOOLS = """import itertools
from typing import Any

from agent_actions import FileUDFResult, udf_tool
from agent_actions.config.schema import Granularity

_CALLS = itertools.count()


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
def fold_version_pick(data: Any, *args) -> list[dict]:
    return [{"item_id": str(_find(data, "item_id"))}]


@udf_tool(granularity=Granularity.FILE)
def fold_version_once(data: list[dict], **kwargs) -> FileUDFResult:
    at = {record["item_id"]: position for position, record in enumerate(data)}
    if next(_CALLS) == 0:
        outputs = [{"source_index": [at["a"], at["b"]], "data": {"tag": "ab"}}]
    else:
        outputs = [{"source_index": at[item], "data": {"tag": item}} for item in "ab"]
    outputs.append({"source_index": at["c"], "data": {"tag": "c"}})
    return FileUDFResult(outputs=outputs)


@udf_tool
def fold_version_merge(data: Any, *args) -> list[dict]:
    tags = [str(data[name]["tag"]) for name in ("check_1", "check_2")]
    return [{"tags": "+".join(sorted(tags))}]
"""

PROMPTS = """{prompt Merge}
Merge these tags.
{{ check_1.tag }} {{ check_2.tag }}
```json
{"tags": "..."}
```
{end_prompt}
"""


def _config(*, run_mode: str, merge: str) -> str:
    merge_body = (
        "    kind: tool\n    impl: fold_version_merge\n"
        if merge == "tool"
        else f"    prompt: ${WORKFLOW}.Merge\n"
    )
    return (
        f"name: {WORKFLOW}\n"
        'description: "a version merge beside a version that folds a record"\n'
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
        "    impl: fold_version_pick\n"
        "    schema: stage_out\n"
        "    context_scope: { observe: [source.item_id] }\n"
        "  - name: check\n"
        "    kind: tool\n"
        '    intent: "a FILE tool that folds b into a in one version"\n'
        "    impl: fold_version_once\n"
        "    granularity: File\n"
        "    versions: { param: pass_no, range: [1, 2] }\n"
        "    schema: check_out\n"
        "    dependencies: [stage]\n"
        "    context_scope: { observe: [stage.item_id] }\n"
        "  - name: merged\n"
        '    intent: "merge the versions"\n' + merge_body + "    schema: merged_out\n"
        "    dependencies: [check]\n"
        "    version_consumption: { source: check, pattern: merge }\n"
        "    context_scope: { observe: [check_1.tag, check_2.tag] }\n"
    )


def _project(root: Path, *, batch: bool = False, merge: str = "tool") -> Path:
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
        _config(run_mode="batch" if batch else "online", merge=merge)
    )
    (workflow / "agent_io" / "staging" / "items.json").write_text(
        json.dumps([{"item_id": "a"}, {"item_id": "b"}, {"item_id": "c"}])
    )
    (root / "tools" / WORKFLOW / "fold_one_version_tools.py").write_text(TOOLS)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(PROMPTS)
    for action, field in (("stage", "item_id"), ("check", "tag"), ("merged", "tags")):
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


def _folding_version(root: Path) -> str:
    (version,) = [name for name in ("check_1", "check_2") if len(_stored(root, name)) == 2]
    return version


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


@pytest.mark.parametrize(
    ("batch", "merge"),
    [(False, "tool"), (False, "llm"), (True, "llm")],
    ids=["online-tool", "online-llm", "batch-llm"],
)
def test_a_record_one_version_folded_is_left_unprocessed_at_the_merge(tmp_path, batch, merge):
    root = _project(tmp_path, batch=batch, merge=merge)

    result = _settle(root)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    a, b, c = (_source_of(root, item) for item in "abc")
    folding = _folding_version(root)
    assert _dispositions(root, folding).get(b) == ("success", "consumed_into_output")
    assert _dispositions(root, "merged").get(b) == CONSUMED, output
    assert _dispositions(root, "merged").get(a, ("success", None))[0] == "success"
    assert _dispositions(root, "merged").get(c, ("success", None))[0] == "success"

    rows = {row["source_guid"]: row for row in _stored(root, "merged")}
    assert rows[b]["content"].get("merged") is None
    assert rows[b]["metadata"]["reason"] == "consumed_into_another_record"
    assert rows[b]["metadata"]["consumed_into"] == a
    assert rows[a]["content"]["merged"] and rows[c]["content"]["merged"]
    if merge == "tool":
        assert rows[a]["content"]["merged"]["tags"] == "a+ab"
        assert rows[c]["content"]["merged"]["tags"] == "c+c"
    if not batch:
        # A batch run reports it when it submits, before the run that collects.
        assert "consumed into another record" in output


def test_agac_dispositions_counts_the_folded_record_unprocessed_at_the_merge(tmp_path):
    root = _project(tmp_path)
    _run(root, "--fresh")

    summary = run_agac(root, "dispositions", "-a", WORKFLOW, "--action", "merged")

    assert summary.returncode == 0, summary.stdout + summary.stderr
    merged_row = next(line for line in summary.stdout.splitlines() if "merged" in line)
    assert [cell.strip() for cell in merged_row.strip("│ ").split("│")][1:5] == [
        "2",
        "0",
        "0",
        "1",
    ]
