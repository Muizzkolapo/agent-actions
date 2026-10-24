"""A version merge reads its other dependencies as a fan-in reads its branches.

A merge's input is its versions' records merged by correlation id. A dependency that
is not one of those versions (a sibling branch of the same upstream) holds records for
the same inputs, and the merge observes its namespace, so the merge pairs them as any
fan-in pairs its branches. Driven through `agac run` and `agac retry` against a copy of
the map/reduce example, with the agac provider mock for the LLM actions.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from tests._support.agac_cli import run_agac
from tests.helpers.trace_store import trace_rows

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "examples" / "map_reduce_fanin_check"
WORKFLOW = "map_reduce_fanin_check"
ITEMS = ["alpha", "beta", "gamma"]

_HEAD = """\
name: map_reduce_fanin_check
description: "a version merge with a sibling dependency"
version: "1.0.0"

defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source:
    type: local
    folder: ./staging
    file_type: [json]

actions:
  - name: stage_items
    kind: tool
    impl: stage_items
    intent: "Stage"
    schema: { item_id: string, text: string }
    context_scope:
      observe: [source.item_id, source.text]

  - name: vote_direct
    kind: tool
    impl: cast_vote_direct
    dependencies: [stage_items]
    intent: "Vote"
    versions: { param: voter_id, range: [1, 2] }
    schema: { vote: string, voted_item: string }
    context_scope:
      observe: [stage_items.*]

  - name: note_direct
    kind: tool
    impl: note_direct
    dependencies: [stage_items]
    intent: "A sibling branch of the versions"
    schema: { note: string }
    context_scope:
      observe: [stage_items.*]
"""

_RECORD_TOOL = """
  - name: tally
    kind: tool
    impl: tally_with_note
    dependencies: [vote_direct, note_direct]
    intent: "Merge the votes with the note"
    version_consumption: { source: vote_direct, pattern: merge }
    schema: { n_votes: integer, note: string }
    context_scope:
      observe: [vote_direct.*, note_direct.*]
"""

_FILE_TOOL = """
  - name: tally
    kind: tool
    impl: tally_file_with_note
    granularity: File
    dependencies: [vote_direct, note_direct]
    intent: "Merge the votes with the note, a file at a time"
    version_consumption: { source: vote_direct, pattern: merge }
    schema: { n_votes: integer, note: string }
    context_scope:
      observe: [vote_direct.*, note_direct.*]
"""

_LLM = """
  - name: tally
    dependencies: [vote_direct, note_direct]
    intent: "Merge the votes with the note"
    run_mode: {mode}
    version_consumption: {{ source: vote_direct, pattern: merge }}
    prompt: "Votes {{{{ vote_direct_1.vote }}}} {{{{ vote_direct_2.vote }}}} NOTE=[{{{{ note_direct.note }}}}]"
    schema: {{ summary: string }}
    context_scope:
      observe: [vote_direct.*, note_direct.*]
"""

_TOOLS = '''\
from pathlib import Path
from typing import Any

from agent_actions import udf_tool
from agent_actions.config.schema import Granularity
from agent_actions.utils.udf_management.registry import FileUDFResult

FAIL_ONCE = Path(__file__).resolve().parents[2] / "fail_beta_once"


def _note(item: dict[str, Any]) -> str:
    note = item.get("note_direct")
    return note["note"] if isinstance(note, dict) and "note" in note else "MISSING"


def _flat_note(item: dict[str, Any]) -> str:
    """A file tool reads each observed field flat, as ``namespace.field``."""
    return str(item.get("note_direct.note", "MISSING"))


@udf_tool()
def tally_with_note(data: dict[str, Any]) -> dict[str, Any]:
    if FAIL_ONCE.exists() and "beta" in json_of(data):
        raise RuntimeError("fails for beta until the marker is removed")
    votes = [k for k in data if k.startswith("vote_direct_")]
    return {"n_votes": len(votes), "note": _note(data)}


def json_of(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, default=str)


@udf_tool(granularity=Granularity.FILE)
def tally_file_with_note(data: list[Any]) -> FileUDFResult:
    outputs = []
    for index, item in enumerate(data):
        item = dict(item)
        votes = {k.split(".")[0] for k in item if k.startswith("vote_direct_")}
        data_out = {"n_votes": len(votes), "note": _flat_note(item)}
        outputs.append({"source_index": index, "data": data_out})
    return FileUDFResult(outputs=outputs)
'''


def _project(tmp_path: Path, tally: str) -> Path:
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_HEAD + tally)
    (root / "tools" / WORKFLOW / "merge_with_note.py").write_text(_TOOLS)
    (root / ".env").write_text("OPENAI_API_KEY=sk-not-used\n")
    return root


def _agac(root: Path, *args: str) -> str:
    result = run_agac(
        root,
        *args,
        "-a",
        WORKFLOW,
        env={"OPENAI_API_KEY": "sk-not-used", "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    return output


def _tally_rows(root: Path) -> list[dict]:
    backend = SQLiteBackend.create_readonly(
        root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.db"
    )
    try:
        rows = backend.connection.execute(
            "SELECT data FROM target_data WHERE action_name = 'tally'"
        ).fetchall()
        return [
            record
            for (data,) in rows
            for record in backend.decode_payload(data, table="target_data", where="tally")
        ]
    finally:
        backend.close()


def _notes(rows: list[dict]) -> list[tuple[int, str]]:
    found = []
    for row in rows:
        content = row.get("content") or {}
        out = content.get("tally") or content
        if isinstance(out, dict) and "note" in out:
            found.append((out["n_votes"], out["note"]))
    return sorted(found, key=lambda pair: pair[1])


EXPECTED = [(2, f"direct-{item}") for item in ITEMS]


def test_a_record_tool_merging_versions_reads_its_sibling_dependency(tmp_path):
    root = _project(tmp_path, _RECORD_TOOL)
    _agac(root, "run", "--fresh")

    assert _notes(_tally_rows(root)) == EXPECTED


def test_a_file_tool_merging_versions_reads_its_sibling_dependency(tmp_path):
    root = _project(tmp_path, _FILE_TOOL)
    _agac(root, "run", "--fresh")

    assert _notes(_tally_rows(root)) == EXPECTED


def test_a_retried_record_of_a_version_merge_reads_its_sibling_dependency(tmp_path):
    root = _project(tmp_path, _RECORD_TOOL)
    (root / "fail_beta_once").write_text("")
    run_agac(root, "run", "-a", WORKFLOW, "--fresh")
    assert [note for _, note in _notes(_tally_rows(root))] == ["direct-alpha", "direct-gamma"]

    (root / "fail_beta_once").unlink()
    _agac(root, "retry")

    assert _notes(_tally_rows(root)) == EXPECTED


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_an_llm_merging_versions_is_prompted_with_its_sibling_dependency(tmp_path, mode):
    root = _project(tmp_path, _LLM.format(mode=mode))
    _agac(root, "run", "--fresh")
    if mode == "batch":
        _agac(root, "run")

    prompts = [
        prompt
        for (prompt,) in trace_rows(
            root, "SELECT compiled_prompt FROM prompt_trace WHERE action_name = 'tally'"
        )
    ]
    assert sorted(set(prompts)) == [f"Votes keep keep NOTE=[direct-{item}]" for item in ITEMS]
    assert len(_tally_rows(root)) == len(ITEMS)
