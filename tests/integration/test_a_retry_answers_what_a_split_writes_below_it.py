"""A retry that re-runs a split for a record answers the split's new rows below it.

`roll_up` turns each record into two rows, each minted an identity of its own. A retry
names the record, and the actions below the split are handed its rows only if they count
as named too. Without that, `finalize` was handed nothing, kept the record's tombstone
from the failed run, and read complete, so no later run answered the rows (#1375).

Each run is its own `agac` process against local tools and the agac provider mock.
`pages2.json` is never touched, so its rows must come through every retry unchanged.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "file_roll"

_HEADER = """\
name: file_roll
description: "A split above the last action"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: flatten
    kind: tool
    intent: "Flatten"
    schema: tool_action_output
    impl: roll_flatten
    context_scope: { observe: [source.page_content] }
    expect: { repair: none }
  - name: roll_up
    kind: tool
    dependencies: [flatten]
    intent: "Roll up"
    schema: tool_action_output
    impl: roll_in_two
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""

_FINALIZE = {
    "tool": """\
  - name: finalize
    kind: tool
    dependencies: [roll_up]
    intent: "Finalize"
    schema: tool_action_output
    impl: roll_finalize
    context_scope: { observe: [roll_up.summary] }
    expect: { repair: none }
""",
    "online": """\
  - name: finalize
    dependencies: [roll_up]
    intent: "Finalize"
    schema: tool_action_output
    prompt: $file_roll.Finalize
    context_scope: { observe: [roll_up.summary] }
""",
}
_FINALIZE["batch"] = _FINALIZE["online"] + "    run_mode: batch\n"

_PROMPTS = """\
{prompt Finalize}
Restate this summary verbatim.
## SUMMARY
{{ roll_up.summary }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}
"""

# The flag file is the fault: while it exists, the action named in FAIL_AT raises for
# alpha. `finalize` logs every summary it is handed.
_TOOLS = """\
from pathlib import Path
from typing import Any

from agent_actions import udf_tool

HERE = Path(__file__).resolve().parents[2]


def _find(data: Any, key: str):
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            hit = _find(value, key)
            if hit is not None:
                return hit
    return None


def _fails(action: str, text: str) -> bool:
    flag = HERE / "FAIL_AT"
    return flag.exists() and flag.read_text().strip() == action and "alpha" in text


@udf_tool
def roll_flatten(data: Any, *args) -> list[dict]:
    page = str(_find(data, "page_content"))
    if _fails("flatten", page):
        raise RuntimeError("alpha fails at flatten")
    return [{"summary": page, "exam_density": "low"}]


@udf_tool
def roll_in_two(data: Any, *args) -> list[dict]:
    summary = str(_find(data, "summary"))
    if _fails("roll_up", summary):
        raise RuntimeError("alpha fails at roll_up")
    return [{"summary": f"{summary} #{half}", "exam_density": "low"} for half in (1, 2)]


@udf_tool
def roll_finalize(data: Any, *args) -> list[dict]:
    summary = str(_find(data, "summary"))
    with (HERE / "handed.log").open("a") as log:
        log.write(summary + "\\n")
    return [{"summary": f"FINAL[{summary}]", "exam_density": "low"}]
"""

ALL_FINAL = [
    "FINAL[Page alpha. #1]",
    "FINAL[Page alpha. #2]",
    "FINAL[Page beta. #1]",
    "FINAL[Page beta. #2]",
]


def _project(tmp_path: Path, finalize: str) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_HEADER + _FINALIZE[finalize])
    staging = workflow / "agent_io" / "staging"
    staging.mkdir(parents=True)
    staging.joinpath("pages1.json").write_text(
        json.dumps([{"page_content": "Page alpha."}, {"page_content": "Page beta."}])
    )
    staging.joinpath("pages2.json").write_text(
        json.dumps([{"page_content": "Page gamma."}, {"page_content": "Page delta."}])
    )
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / "tools" / WORKFLOW).mkdir()
    (root / "tools" / WORKFLOW / "roll_tools.py").write_text(_TOOLS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _agac(project: Path, *args: str) -> str:
    result = run_agac(project, *args, env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"})
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    return output


def _run(project: Path, *args: str) -> str:
    output = _agac(project, "run", "-a", WORKFLOW, *args)
    if "Run again" in output:
        output += _agac(project, "run", "-a", WORKFLOW)
    return output


def _rows(project: Path, action: str, path: str) -> list[dict]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        blobs = [
            row[0]
            for row in con.execute(
                "select data from target_data where action_name = ? and relative_path = ?",
                (action, path),
            )
        ]
    finally:
        con.close()
    rows: list[dict] = []
    for blob in blobs:
        loaded = json.loads(blob)
        rows.extend(loaded if isinstance(loaded, list) else [loaded])
    return rows


def _dispositions(project: Path, action: str) -> dict[str, str]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return dict(
            con.execute(
                "select record_id, disposition from record_disposition where action_name = ?",
                (action,),
            ).fetchall()
        )
    finally:
        con.close()


def _summaries(project: Path, action: str, path: str) -> list[str]:
    return sorted(
        str(((row.get("content") or {}).get(action) or {}).get("summary"))
        for row in _rows(project, action, path)
    )


def _handed(project: Path) -> list[str]:
    log = project / "handed.log"
    return sorted(log.read_text().splitlines()) if log.exists() else []


def _retried(tmp_path: Path, finalize: str, fail_at: str) -> tuple[Path, str, list[dict]]:
    """A run that fails alpha at *fail_at*, then a retry once the fault is gone."""
    project = _project(tmp_path, finalize)
    (project / "FAIL_AT").write_text(fail_at)
    _run(project, "--fresh")
    assert any(
        row.get("_state") == "cascade_skipped" for row in _rows(project, "finalize", "pages1.json")
    ), "the failed run left no tombstone below the split"
    untouched = _rows(project, "finalize", "pages2.json")
    (project / "FAIL_AT").unlink()
    (project / "handed.log").unlink(missing_ok=True)
    output = _agac(project, "retry", "-a", WORKFLOW)
    if finalize == "batch":
        output += _run(project)
    return project, output, untouched


@pytest.mark.parametrize("fail_at", ["flatten", "roll_up"])
class TestAToolBelowTheSplit:
    def test_it_answers_each_row_the_split_wrote_for_the_record(self, tmp_path, fail_at):
        project, output, _ = _retried(tmp_path, "tool", fail_at)

        assert _handed(project) == ["Page alpha. #1", "Page alpha. #2"], output
        assert _summaries(project, "finalize", "pages1.json") == ALL_FINAL

    def test_it_keeps_no_tombstone_and_no_unanswered_row(self, tmp_path, fail_at):
        project, _, _ = _retried(tmp_path, "tool", fail_at)

        rows = _rows(project, "finalize", "pages1.json")
        assert [row["_state"] for row in rows] == ["processed"] * 4
        answered = {
            guid for guid, d in _dispositions(project, "finalize").items() if d == "success"
        }
        assert {row["source_guid"] for row in rows} <= answered

    def test_the_untouched_file_comes_through_as_it_was(self, tmp_path, fail_at):
        project, _, untouched = _retried(tmp_path, "tool", fail_at)

        assert _rows(project, "finalize", "pages2.json") == untouched

    def test_the_next_run_has_nothing_left_to_answer(self, tmp_path, fail_at):
        project, _, _ = _retried(tmp_path, "tool", fail_at)
        before = _rows(project, "finalize", "pages1.json")
        (project / "handed.log").unlink(missing_ok=True)

        output = _run(project)

        assert output.count("already complete") == 3, output
        assert _handed(project) == []
        assert _rows(project, "finalize", "pages1.json") == before


@pytest.mark.parametrize("mode", ["online", "batch"])
class TestAnLlmActionBelowTheSplit:
    def test_it_answers_each_row_the_split_wrote_for_the_record(self, tmp_path, mode):
        project, output, _ = _retried(tmp_path, mode, "flatten")

        rows = _rows(project, "finalize", "pages1.json")
        assert [row["_state"] for row in rows] == ["processed"] * 4, output
        split = {row["source_guid"] for row in _rows(project, "roll_up", "pages1.json")}
        assert {row["source_guid"] for row in rows} == split

    def test_the_untouched_file_comes_through_as_it_was(self, tmp_path, mode):
        project, _, untouched = _retried(tmp_path, mode, "flatten")

        assert _rows(project, "finalize", "pages2.json") == untouched

    def test_the_next_run_has_nothing_left_to_answer(self, tmp_path, mode):
        project, _, _ = _retried(tmp_path, mode, "flatten")
        before = _rows(project, "finalize", "pages1.json")

        output = _run(project)

        assert output.count("already complete") == 3, output
        assert _rows(project, "finalize", "pages1.json") == before
