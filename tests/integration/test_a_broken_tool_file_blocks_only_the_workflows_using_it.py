"""A tool file that fails to import blocks only a workflow using a tool from it (1608).

It used to stop discovery, so every workflow in the project failed to start. Now a run
warns and skips the file; a workflow naming one of its tools is refused at preflight, before
any action runs, by an error naming the file. Each run is an ``agac run``.
"""

import json
import shutil
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "uses_good"

CONFIG = """name: uses_good
description: "two tool actions"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: first
    kind: tool
    impl: good_first
    intent: "First"
    schema: {{ a: string }}
    context_scope: {{ observe: [source.page_id] }}
  - name: second
    kind: tool
    impl: {second}
    dependencies: [first]
    intent: "Second"
    schema: {{ b: string }}
    context_scope: {{ observe: [first.a] }}
"""

GOOD = """from typing import Any

from agent_actions import udf_tool


@udf_tool()
def good_first(data: dict[str, Any]) -> dict[str, Any]:
    with open("first.log", "a") as log:
        log.write("ran\\n")
    return {"a": "x"}


@udf_tool()
def good_second(data: dict[str, Any]) -> dict[str, Any]:
    return {"b": "y"}
"""

BROKEN = """from agent_actions import udf_tool


@udf_tool()
def broken_second(data):
    return {"b": "z"}


raise RuntimeError("boom at import")
"""


def _project(tmp_path, second):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(CONFIG.format(second=second))
    (directory / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": "p0", "page_content": "x"}])
    )
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "good.py").write_text(GOOD)
    (root / "tools" / "elsewhere").mkdir()
    (root / "tools" / "elsewhere" / "broken.py").write_text(BROKEN)
    return root


def _run(root):
    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")
    return result.returncode, " ".join((result.stdout + result.stderr).split())


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


def test_a_workflow_using_none_of_its_tools_runs_and_names_the_skipped_file(tmp_path):
    root = _project(tmp_path, "good_second")

    code, output = _run(root)

    assert code == 0, output
    assert "Skipped tool file" in output
    assert "broken.py: it failed to import (boom at import)" in output
    assert "2 completed" in output


def test_a_workflow_using_one_of_its_tools_is_refused_before_any_action_runs(tmp_path):
    root = _project(tmp_path, "broken_second")

    code, output = _run(root)

    assert code != 0
    assert "Function 'broken_second' not found" in output
    assert "Action 'second' names it" in output
    assert "These tool files failed to import and were skipped:" in output
    assert "broken.py: boom at import" in output
    assert not (root / "first.log").exists(), "an action ran before the refusal"
