"""A retry of one record keeps the failed row an action stored for a record with no identity.

A record that reaches an action without a source_guid is refused: the action stores a
failed row with no source_guid and records no disposition for it, so that row and the run
log are the only record of the refusal. A repair names records by source_guid, so it can
never name that one, and it replaced the file with what it produced plus the stored rows
it handed back -- none of them without a source_guid. The row was gone after the retry
of any other record, and the action read complete, so no later run wrote it again.

Each run is its own `agac` process. `flatten` is a tool; `stamp` reads it, a tool online
and an LLM action under batch. One stored `flatten` row loses its source_guid, as an
upstream file edited by hand would leave it, and `stamp`'s schema is edited and the next
run names it with ``--rerun`` so it answers every record again.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "nameless_kept"

_CONFIG = """\
name: nameless_kept
description: "A record tool, and an action below it"
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
  - name: flatten
    kind: tool
    intent: "Flatten"
    schema: nameless_kept_output
    impl: nameless_kept_flatten
    context_scope: {{ observe: [source.page_content] }}
  - name: stamp
{stamp}
    dependencies: [flatten]
    intent: "Stamp"
    schema: {schema}
    context_scope: {{ observe: [flatten.summary] }}
"""

_STAMP = {
    "online": "    kind: tool\n    impl: nameless_kept_stamp",
    "batch": "    run_mode: batch\n    prompt: $nameless_kept.Stamp",
}

_SCHEMA = """\
name: {name}
fields:
  - id: summary
    type: string
  - id: exam_density
    type: string
additionalProperties: true
"""

_PROMPTS = """\
{prompt Stamp}
Restate this summary verbatim.
{{ flatten.summary }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}
"""

_FLATTEN = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def nameless_kept_flatten(data: Any, *args) -> list[dict]:
    page = str(((data or {}).get("source") or {}).get("page_content", ""))
    return [{"summary": page, "exam_density": "low"}]
"""

_STAMP_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def nameless_kept_stamp(data: Any, *args) -> list[dict]:
    summary = str(((data or {}).get("flatten") or {}).get("summary", ""))
    return [{"summary": f"stamped {summary}", "exam_density": "low"}]
"""


def _project(tmp_path: Path, mode: str) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    staging = workflow / "agent_io" / "staging"
    staging.mkdir(parents=True)
    pages = [{"page_content": f"Page {n}."} for n in range(4)]
    (staging / "pages.json").write_text(json.dumps(pages))
    tools = root / "tools" / WORKFLOW
    tools.mkdir(parents=True)
    (tools / "nameless_kept_flatten.py").write_text(_FLATTEN)
    (tools / "nameless_kept_stamp.py").write_text(_STAMP_TOOL)
    schemas = root / "schema" / WORKFLOW
    schemas.mkdir()
    for name in ("nameless_kept_output", "nameless_kept_edited"):
        (schemas / f"{name}.yml").write_text(_SCHEMA.format(name=name))
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    _configure(root, mode, "nameless_kept_output")
    return root


def _configure(project: Path, mode: str, schema: str) -> None:
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(_CONFIG.format(stamp=_STAMP[mode], schema=schema))


_ENV = {"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}


def _run(project: Path, *first: str) -> None:
    """`agac run` until nothing is left in flight, passing *first* to the first run alone."""
    args = first
    for _ in range(4):
        result = run_agac(project, "run", "-a", WORKFLOW, "-u", "tools", *args, env=_ENV)
        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        if "run again" not in output:
            return
        args = ()
    pytest.fail(f"the workflow never stopped asking to be run again:\n{output}")


def _backend(project: Path):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _held(project: Path, action: str = "stamp") -> list[dict]:
    backend = _backend(project)
    try:
        (path,) = backend.list_target_files(action)
        return backend.read_target_for_rewrite(action, path)
    finally:
        backend.close()


def _refused_at_stamp(project: Path, mode: str) -> dict:
    """Edit one stored `flatten` row out of its identity, and run `stamp` again over it.

    Returns the failed row `stamp` stored for it.
    """
    backend = _backend(project)
    try:
        (path,) = backend.list_target_files("flatten")
        rows = backend.read_target_for_rewrite("flatten", path)
        rows[0]["source_guid"] = None
        backend.write_target("flatten", path, rows, force_full=True)
    finally:
        backend.close()
    _configure(project, mode, "nameless_kept_edited")
    _run(project, "--rerun", "stamp")
    (refused,) = [row for row in _held(project) if not row.get("source_guid")]
    assert refused["_state"] == "failed"
    return refused


def _fail_one_answer(project: Path) -> str:
    """Mark one of `stamp`'s answered records failed, for `agac retry` to repair."""
    backend = _backend(project)
    try:
        guid = next(row["source_guid"] for row in _held(project) if row.get("source_guid"))
        backend.set_disposition("stamp", guid, "failed", reason="set by the test")
    finally:
        backend.close()
    return guid


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_a_retry_of_another_record_keeps_the_failed_row_of_a_record_with_no_source_guid(
    tmp_path, mode
):
    project = _project(tmp_path, mode)
    _run(project, "--fresh")
    refused = _refused_at_stamp(project, mode)
    answered = sorted(row["source_guid"] for row in _held(project) if row.get("source_guid"))
    repaired = _fail_one_answer(project)

    result = run_agac(project, "retry", "-a", WORKFLOW, env=_ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    _run(project)

    held = _held(project)
    assert sorted(row["source_guid"] for row in held if row.get("source_guid")) == answered
    assert [row for row in held if not row.get("source_guid")] == [refused]
    (row,) = [row for row in held if row.get("source_guid") == repaired]
    assert row["_state"] == "processed"


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_a_plain_run_over_the_record_with_no_source_guid_stores_its_failed_row_once(tmp_path, mode):
    """It refuses the record again and writes that row, carrying none stored beside it."""
    project = _project(tmp_path, mode)
    _run(project, "--fresh")
    _refused_at_stamp(project, mode)
    _configure(project, mode, "nameless_kept_output")

    _run(project, "--rerun", "stamp")

    held = _held(project)
    assert len(held) == 4
    assert [row["_state"] for row in held if not row.get("source_guid")] == ["failed"]
