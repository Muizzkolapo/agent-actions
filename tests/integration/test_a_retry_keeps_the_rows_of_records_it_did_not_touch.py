"""A retry of one record keeps the rows of every record whose input did not change.

The shape of the report (1876): a record tool splits each page into two concepts, a
FILE tool catalogues them, an LLM action with a guard judges the first concept of
each page and skips the second, a second FILE tool routes the two concepts of a
page into one row, and an LLM action answers each route.

Four pages in one file. `split` fails gamma while a flag exists, which is the
fault the retry repairs. The catalogue row of `alpha #1` lists the pages the file
holds, so gamma coming back changes it, and only it: that record and what is built
on it are answered again. Every other record of the file keeps its stored rows in
every action below, and no LLM call is made for it.

Each run is its own `agac` process.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.cli.exit_codes import EXIT_RECORD_FAILURES, EXIT_SUCCESS
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "keep_untouched"
PAGES = ["alpha", "beta", "gamma", "delta"]
BELOW = ["catalogue", "judge", "route", "answer"]
LLM_ACTIONS = ["judge", "answer"]

_SCHEMA = """\
name: keep_untouched_output
fields:
  - id: concept
    type: string
  - id: peers
    type: string
additionalProperties: true
"""

_VERDICT_SCHEMA = """\
name: keep_untouched_verdict
fields:
  - id: verdict
    type: string
"""

# Module names no other fixture uses: discovery imports tools by module name.
_SPLIT = """\
import os
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


@udf_tool
def keep_split(data: Any, *args) -> list[dict]:
    page = str(((data or {}).get("source") or {}).get("page", ""))
    if page == "gamma" and (Path(os.environ["KEEP_DIR"]) / "fail_gamma").exists():
        raise RuntimeError("gamma fails while the flag exists")
    return [{"concept": f"{page} #{n}", "peers": page} for n in (1, 2)]
"""

# One row per concept. Only `alpha #1` reads the other pages of the file.
_CATALOGUE = """\
from agent_actions import FileUDFResult, udf_tool
from agent_actions.config.schema import Granularity


@udf_tool(granularity=Granularity.FILE)
def keep_catalogue(data: list) -> FileUDFResult:
    pages = sorted({item["concept"].split(" ")[0] for item in data})
    return FileUDFResult(
        outputs=[
            {
                "source_index": i,
                "data": {
                    "concept": item["concept"],
                    "peers": " ".join(pages) if item["concept"] == "alpha #1" else item["concept"],
                    "rank": item["concept"].split("#")[1],
                },
            }
            for i, item in enumerate(data)
        ]
    )
"""

# One row per page, made from both its concepts, first concept first, so each row lists
# several sources and is built on the concept the guard let through.
_ROUTE = """\
from agent_actions import FileUDFResult, udf_tool
from agent_actions.config.schema import Granularity


@udf_tool(granularity=Granularity.FILE)
def keep_route(data: list) -> FileUDFResult:
    at: dict[str, list[int]] = {}
    for i in sorted(range(len(data)), key=lambda i: data[i]["concept"]):
        at.setdefault(data[i]["concept"].split(" ")[0], []).append(i)
    return FileUDFResult(
        outputs=[
            {
                "source_index": positions,
                "data": {
                    "concept": data[positions[0]]["concept"],
                    "peers": data[positions[0]]["peers"],
                    "verdict": data[positions[0]].get("verdict"),
                },
            }
            for positions in at.values()
        ]
    )
"""

CONFIG = """\
name: keep_untouched
description: "Two FILE tools and two LLM actions below a record tool"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: agac-model
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: split
    kind: tool
    intent: "Split a page into concepts"
    schema: keep_untouched_output
    impl: keep_split
    context_scope: { observe: [source.page] }
  - name: catalogue
    kind: tool
    granularity: File
    dependencies: [split]
    intent: "Catalogue the concepts"
    schema: keep_untouched_output
    impl: keep_catalogue
    context_scope: { observe: [split.concept] }
  - name: judge
    dependencies: [catalogue]
    intent: "Judge a concept"
    schema: keep_untouched_verdict
    prompt: $keep_untouched.Judge
    context_scope: { observe: [catalogue.concept, catalogue.peers] }
    guard: { condition: 'catalogue.rank == "1"', on_false: skip }
  - name: route
    kind: tool
    granularity: File
    dependencies: [judge]
    intent: "Route the concepts of a page"
    schema: keep_untouched_output
    impl: keep_route
    context_scope: { observe: [catalogue.concept, catalogue.peers, judge.verdict] }
  - name: answer
    dependencies: [route]
    intent: "Answer a route"
    schema: keep_untouched_verdict
    prompt: $keep_untouched.Answer
    context_scope: { observe: [route.concept, route.peers] }
"""

_PROMPTS = """\
{prompt Judge}
Judge this concept.
{{ catalogue.concept }} {{ catalogue.peers }}
```json
{"verdict": "..."}
```
{end_prompt}

{prompt Answer}
Answer this route.
{{ route.concept }} {{ route.peers }}
```json
{"verdict": "..."}
```
{end_prompt}
"""


def _project(tmp_path: Path, config: str = CONFIG) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(config)
    staging = workflow / "agent_io" / "staging"
    staging.mkdir(parents=True)
    (staging / "pages.json").write_text(json.dumps([{"page": page} for page in PAGES]))
    tools = root / "tools" / WORKFLOW
    tools.mkdir(parents=True)
    (tools / "keep_split.py").write_text(_SPLIT)
    (tools / "keep_catalogue.py").write_text(_CATALOGUE)
    (tools / "keep_route.py").write_text(_ROUTE)
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "keep_untouched_output.yml").write_text(_SCHEMA)
    (root / "schema" / WORKFLOW / "keep_untouched_verdict.yml").write_text(_VERDICT_SCHEMA)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _env(project: Path) -> dict[str, str]:
    return {"KEEP_DIR": str(project)}


def _agac(project: Path, *args: str, ends_with: int) -> None:
    result = run_agac(project, *args, env=_env(project))
    assert result.returncode == ends_with, result.stdout + result.stderr


def _backend(project: Path):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _stored(project: Path) -> dict[str, dict[str, dict]]:
    """Per action below `split`, each stored row by its identity, less its history."""
    backend = _backend(project)
    try:
        held: dict[str, dict[str, dict]] = {}
        for action in BELOW:
            rows = backend.read_target_for_rewrite(action, "pages.json")
            held[action] = {
                row["source_guid"]: {k: v for k, v in row.items() if k != "_state_history"}
                for row in rows
            }
        return held
    finally:
        backend.close()


def _calls(project: Path) -> dict[str, list[str]]:
    """Per LLM action, the record of each prompt sent to it, in order."""
    backend = _backend(project)
    try:
        return {
            action: [
                row[0]
                for row in backend.connection.execute(
                    "SELECT source_guid FROM prompt_trace WHERE action_name = ? ORDER BY id",
                    (action,),
                )
            ]
            for action in LLM_ACTIONS
        }
    finally:
        backend.close()


def _concept(row: dict, action: str) -> str:
    """The concept a row is built on, read from the nearest action that names one."""
    content = row.get("content") or {}
    for namespace in (action, "route", "catalogue"):
        concept = (content.get(namespace) or {}).get("concept")
        if concept:
            return concept
    return ""


def _page(row: dict, action: str) -> str:
    return _concept(row, action).split(" ")[0]


def _retry_gamma(tmp_path: Path):
    """The rows each action held before and after a retry of gamma, and the prompts
    each LLM action was sent by the retry alone."""
    project = _project(tmp_path)
    _agac(project, "run", "-a", WORKFLOW, "-u", "tools", "--fresh", ends_with=EXIT_SUCCESS)
    (project / "fail_gamma").touch()
    _agac(
        project,
        "run",
        "-a",
        WORKFLOW,
        "-u",
        "tools",
        "--rerun",
        "split",
        ends_with=EXIT_RECORD_FAILURES,
    )
    (project / "fail_gamma").unlink()
    before = _stored(project)
    calls_before = _calls(project)

    _agac(project, "retry", "-a", WORKFLOW, ends_with=EXIT_SUCCESS)

    after = _stored(project)
    calls = {action: sent[len(calls_before[action]) :] for action, sent in _calls(project).items()}
    return before, after, calls


@pytest.fixture(scope="module")
def retried(tmp_path_factory):
    return _retry_gamma(tmp_path_factory.mktemp("retried"))


def _untouched(rows: dict[str, dict], action: str) -> dict[str, dict]:
    """The rows of *rows* built on a concept whose catalogue row gamma does not change."""
    return {
        guid: row
        for guid, row in rows.items()
        if _page(row, action) in ("beta", "delta") or _concept(row, action) == "alpha #2"
    }


def test_the_premise_gamma_was_missing_and_comes_back(retried):
    before, after, calls = retried

    assert "gamma" not in {_page(row, "route") for row in before["route"].values()}
    assert "gamma" in {_page(row, "route") for row in after["route"].values()}
    routed = [row for row in before["route"].values() if row["_state"] == "processed"]
    assert routed and all(row.get("lineage_sources") for row in routed)
    assert all(calls.values())


@pytest.mark.parametrize("action", BELOW)
def test_every_row_of_a_record_whose_input_did_not_change_is_kept(retried, action):
    before, after, _ = retried
    untouched = _untouched(before[action], action)
    assert untouched

    assert {guid: after[action].get(guid) for guid in untouched} == untouched


@pytest.mark.parametrize("action", LLM_ACTIONS)
def test_no_llm_call_is_made_for_a_record_whose_input_did_not_change(retried, action):
    before, _, calls = retried
    untouched = _untouched(before[action], action)
    assert untouched

    assert untouched.keys().isdisjoint(calls[action])


@pytest.mark.parametrize("action", BELOW)
def test_a_record_whose_input_changed_is_answered_again(retried, action):
    """`alpha #1` now lists gamma among its peers, and so does what is built on it."""
    before, after, calls = retried
    (was,) = [row for row in before[action].values() if _concept(row, action) == "alpha #1"]
    (now,) = [row for row in after[action].values() if _concept(row, action) == "alpha #1"]

    assert "gamma" not in json.dumps(was["content"])
    assert "gamma" in json.dumps(now["content"])
    if action in LLM_ACTIONS:
        assert now["source_guid"] in calls[action]
