"""A run whose final action ends holding no record warns, though every action is green (1612).

Its summary counted actions, not records, so a run whose last action's guard filtered every
record read as a healthy one. Each run is an ``agac run``.
"""

import json
import shutil
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "final_output"

CONFIG = """name: final_output
description: "the last action's guard decides what comes out"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: tag
    kind: tool
    impl: final_output_tag
    intent: "Tag"
    schema: {{ t: string }}
    context_scope: {{ observe: [source.page_id] }}
  - name: write_out
    kind: tool
    impl: final_output_write
    dependencies: [tag]
    intent: "Write"
    guard: {{ condition: 'tag.t == "{keep}"', on_false: filter }}
    schema: {{ o: string }}
    context_scope: {{ observe: [tag.t] }}
"""

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool()
def final_output_tag(data: dict[str, Any]) -> dict[str, Any]:
    return {"t": "x"}


@udf_tool()
def final_output_write(data: dict[str, Any]) -> dict[str, Any]:
    return {"o": "y"}
"""


def _run(tmp_path, keep):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(CONFIG.format(keep=keep))
    (directory / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": "p0", "page_content": "a"}, {"page_id": "p1", "page_content": "b"}])
    )
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "final.py").write_text(TOOLS)
    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")
    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode == 0, output
    return output


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


def test_a_final_action_left_empty_is_named_in_the_summary(tmp_path):
    output = _run(tmp_path, "never")

    assert "No records reached the final output: write_out" in output
    assert "agac dispositions -a final_output --action write_out says why" in output


def test_a_final_action_holding_records_is_not(tmp_path):
    output = _run(tmp_path, "x")

    assert "No records reached the final output" not in output
