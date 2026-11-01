"""``additionalProperties: true`` at the root of an array schema lets a tool carry fields it
does not list, through to an action that reads them (1610). Each run is an ``agac run``."""

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "carry"

CONFIG = """name: carry
description: "a tool carries a field its schema does not list"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: merge
    kind: tool
    impl: carry_through
    intent: "Merge"
    schema: merged
    context_scope: { observe: [source.page_id] }
  - name: read_carried
    kind: tool
    impl: read_carried
    dependencies: [merge]
    intent: "Read what merge carried"
    schema: { got: string }
    context_scope: { observe: [merge.declared, merge.carried] }
"""

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool()
def carry_through(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"declared": "d", "carried": "c"}]


@udf_tool()
def read_carried(data: dict[str, Any]) -> dict[str, Any]:
    return {"got": str((data.get("merge") or {}).get("carried"))}
"""

SCHEMA = """name: merged
type: array
{flag}items:
  type: object
  properties:
    declared: {{type: string}}
  required: [declared]
"""


def _project(tmp_path, flag):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(CONFIG)
    (directory / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": "p0", "page_content": "x"}])
    )
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "carry.py").write_text(TOOLS)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "merged.yml").write_text(SCHEMA.format(flag=flag))
    return root


def _got(root):
    backend = get_storage_backend(
        workflow_path=str(root / "agent_workflow" / WORKFLOW), workflow_name=WORKFLOW
    )
    backend.initialize()
    try:
        return [
            row["content"]["read_carried"]["got"]
            for path in backend.list_target_files("read_carried")
            for row in backend.read_target("read_carried", path)
        ]
    finally:
        backend.close()


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


def test_the_root_flag_lets_the_carried_field_through(tmp_path):
    root = _project(tmp_path, "additionalProperties: true\n")

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _got(root) == ["c"]


def test_without_the_flag_preflight_refuses_a_read_of_the_carried_field(tmp_path):
    root = _project(tmp_path, "")

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode != 0
    assert "Field 'carried' not found in action 'merge' output schema" in output
