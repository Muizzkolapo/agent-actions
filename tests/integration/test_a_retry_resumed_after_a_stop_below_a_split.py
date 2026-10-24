"""A retry stopped after a split it re-ran wrote, and then resumed, answers below the split.

`roll_up` turns each record into two rows, each minted an identity of its own. A retry
that repairs alpha above it re-runs the split for alpha, and before each action below
runs it takes out what that action built on the rows the split replaced: here alpha's
tombstone from the failed run. Those rows are known only from what the split wrote in
that run. Stopped before `finalize` ran, the next `agac retry` re-ran the split over the
rows the stopped one wrote, found nothing of the original taken away, and kept alpha's
tombstone in `finalize` beside the new answers ("cannot be attributed"), reading complete
(1519).

`side` sits between the split and `finalize`, so the stop falls between levels: it
raises KeyboardInterrupt while a flag file exists. Each run is its own `agac` process
against local tools and the agac provider mock. `pages2.json` is never touched.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "file_roll"

_HEADER = """\
name: file_roll
description: "A split, an action below it, and the last action"
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
    impl: resume_flatten
    context_scope: { observe: [source.page_content] }
    expect: { repair: none }
  - name: roll_up
    kind: tool
    dependencies: [flatten]
    intent: "Roll up"
    schema: tool_action_output
    impl: resume_in_two
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
  - name: side
    kind: tool
    dependencies: [roll_up]
    intent: "Pass along"
    schema: tool_action_output
    impl: resume_side
    context_scope: { observe: [roll_up.summary] }
    expect: { repair: none }
"""

_FINALIZE = {
    "tool": """\
  - name: finalize
    kind: tool
    dependencies: [side]
    intent: "Finalize"
    schema: tool_action_output
    impl: resume_finalize
    context_scope: { observe: [side.summary] }
    expect: { repair: none }
""",
    "batch": """\
  - name: finalize
    dependencies: [side]
    intent: "Finalize"
    schema: tool_action_output
    prompt: $file_roll.Finalize
    context_scope: { observe: [side.summary] }
    run_mode: batch
""",
}

_PROMPTS = """\
{prompt Finalize}
Restate this summary verbatim.
## SUMMARY
{{ side.summary }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}
"""

# FAIL_AT fails alpha at flatten; STOP stops the process at side.
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


@udf_tool
def resume_flatten(data: Any, *args) -> list[dict]:
    page = str(_find(data, "page_content"))
    if (HERE / "FAIL_AT").exists() and "alpha" in page:
        raise RuntimeError("alpha fails at flatten")
    return [{"summary": page, "exam_density": "low"}]


@udf_tool
def resume_in_two(data: Any, *args) -> list[dict]:
    summary = str(_find(data, "summary"))
    return [{"summary": f"{summary} #{half}", "exam_density": "low"} for half in (1, 2)]


@udf_tool
def resume_side(data: Any, *args) -> list[dict]:
    if (HERE / "STOP").exists():
        raise KeyboardInterrupt
    return [{"summary": str(_find(data, "summary")), "exam_density": "low"}]


@udf_tool
def resume_finalize(data: Any, *args) -> list[dict]:
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
    (root / "tools" / WORKFLOW / "resume_split_tools.py").write_text(_TOOLS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _agac(project: Path, *args: str, code: int = 0) -> str:
    result = run_agac(project, *args, env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"})
    output = result.stdout + result.stderr
    assert result.returncode == code, output
    return output


def _run(project: Path, *args: str) -> str:
    output = _agac(project, "run", "-a", WORKFLOW, *args)
    if "run again" in output.lower():
        output += _agac(project, "run", "-a", WORKFLOW)
    return output


def _rows(project: Path, action: str, path: str) -> list[dict]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    blobs = [
        row[0]
        for row in stored_rows(
            db,
            "select data from target_data where action_name = ? and relative_path = ?",
            action,
            path,
        )
    ]
    rows: list[dict] = []
    for blob in blobs:
        loaded = json.loads(blob)
        rows.extend(loaded if isinstance(loaded, list) else [loaded])
    return rows


def _summaries(project: Path, action: str, path: str) -> list[str]:
    return sorted(
        str(((row.get("content") or {}).get(action) or {}).get("summary"))
        for row in _rows(project, action, path)
    )


def _statuses(project: Path) -> dict[str, str]:
    path = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return {name: entry["status"] for name, entry in json.loads(path.read_text()).items()}


def _resumed(tmp_path: Path, finalize: str) -> tuple[Path, str, list[dict]]:
    """Fail alpha, stop the retry at side, then retry again with nothing in the way."""
    project = _project(tmp_path, finalize)
    (project / "FAIL_AT").write_text("flatten")
    _run(project, "--fresh")
    (project / "FAIL_AT").unlink()
    assert any(
        row.get("_state") == "cascade_skipped" for row in _rows(project, "finalize", "pages1.json")
    ), "the failed run left no tombstone below the split"
    untouched = _rows(project, "finalize", "pages2.json")

    (project / "STOP").write_text("")
    stopped = _agac(project, "retry", "-a", WORKFLOW, code=130)
    (project / "STOP").unlink()
    assert _statuses(project)["finalize"] == "pending", stopped
    assert _summaries(project, "roll_up", "pages1.json") == [
        "Page alpha. #1",
        "Page alpha. #2",
        "Page beta. #1",
        "Page beta. #2",
    ], stopped

    output = _agac(project, "retry", "-a", WORKFLOW)
    if finalize == "batch":
        output += _run(project)
    return project, output, untouched


@pytest.mark.parametrize("finalize", ["tool", "batch"])
class TestAResumedRetry:
    def test_it_keeps_no_tombstone_below_the_split(self, tmp_path, finalize):
        project, output, _ = _resumed(tmp_path, finalize)

        rows = _rows(project, "finalize", "pages1.json")
        assert [row.get("_state") for row in rows] == ["processed"] * 4, output
        assert "cannot be attributed" not in output, output
        if finalize == "tool":
            assert _summaries(project, "finalize", "pages1.json") == ALL_FINAL

    def test_its_rows_below_are_the_split_rows(self, tmp_path, finalize):
        project, output, _ = _resumed(tmp_path, finalize)

        split = {row["source_guid"] for row in _rows(project, "side", "pages1.json")}
        answered = {row["source_guid"] for row in _rows(project, "finalize", "pages1.json")}
        assert answered == split, output

    def test_the_untouched_file_comes_through_as_it_was(self, tmp_path, finalize):
        project, _, untouched = _resumed(tmp_path, finalize)

        assert _rows(project, "finalize", "pages2.json") == untouched

    def test_the_next_run_has_nothing_left_to_answer(self, tmp_path, finalize):
        project, _, _ = _resumed(tmp_path, finalize)
        before = _rows(project, "finalize", "pages1.json")

        output = _run(project)

        assert output.count("already complete") == 4, output
        assert _rows(project, "finalize", "pages1.json") == before
