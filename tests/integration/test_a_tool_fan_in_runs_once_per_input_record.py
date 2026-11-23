"""A tool action that joins two branches runs once per input record.

Three rows go through two branch actions and a joining action that depends on both.
The run goes through the real CLI, loader and expander.
"""

import json
from pathlib import Path

from tests._support.agac_cli import run_agac

WORKFLOW = "fan_in_probe"
JOINED = "joined"

ROWS = [
    {"parent_id": "X", "text": "one"},
    {"parent_id": "X", "text": "two"},
    {"parent_id": "Y", "text": "three"},
]

TOOLS = '''"""Two branches over one row, and an action that joins them."""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def probe_left(data: dict[str, Any]) -> dict[str, Any]:
    source = data.get("source") or {}
    return {"parent_id": source.get("parent_id", ""), "left_note": f"L:{source.get('text', '')}"}


@udf_tool()
def probe_right(data: dict[str, Any]) -> dict[str, Any]:
    source = data.get("source") or {}
    return {"parent_id": source.get("parent_id", ""), "right_note": f"R:{source.get('text', '')}"}


@udf_tool()
def probe_join(data: dict[str, Any]) -> dict[str, Any]:
    left = data.get("left") or {}
    right = data.get("right") or {}
    return {
        "parent_id": left.get("parent_id", ""),
        "joined": f"{left.get('left_note', '')}|{right.get('right_note', '')}",
    }
'''

WORKFLOW_YML = """\
name: fan_in_probe
description: "Two branches joined by one action"
version: "1.0.0"
defaults:
  json_mode: true
  granularity: Record
  is_operational: true
  run_mode: online
  model_vendor: agac-provider
  model_name: agac-mock
  api_key: AGAC_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: left
    kind: tool
    impl: probe_left
    intent: "One branch"
    schema: { parent_id: string, left_note: string }
    context_scope: { observe: [source.parent_id, source.text] }

  - name: right
    kind: tool
    impl: probe_right
    intent: "The other branch"
    schema: { parent_id: string, right_note: string }
    context_scope: { observe: [source.parent_id, source.text] }

  - name: joined
    kind: tool
    impl: probe_join
    dependencies: [left, right]
    intent: "Join both branches"
    schema: { parent_id: string, joined: string }
    context_scope: { observe: [left.parent_id, left.left_note, right.right_note] }
"""

PROJECT_YML = """\
default_agent_config:
  api_key: AGAC_API_KEY
  prompt_debug: False
schema_path: schema
tool_path: ["tools"]
"""


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    workflow_dir = root / "agent_workflow" / WORKFLOW
    (workflow_dir / "agent_config").mkdir(parents=True)
    (workflow_dir / "agent_io" / "staging").mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "schema").mkdir()

    (root / "agent_actions.yml").write_text(PROJECT_YML)
    (root / ".env").write_text("AGAC_API_KEY=not-used\n")
    (workflow_dir / "agent_config" / f"{WORKFLOW}.yml").write_text(WORKFLOW_YML)
    (workflow_dir / "agent_io" / "staging" / "rows.json").write_text(json.dumps(ROWS))
    (root / "tools" / WORKFLOW / "probe_tools.py").write_text(TOOLS)
    return root


def test_the_joining_action_runs_once_per_input_record(tmp_path):
    project = _project(tmp_path)

    result = run_agac(project, "run", "-w", WORKFLOW, "--fresh")
    output = " ".join((result.stdout + result.stderr).split())

    assert result.returncode == 0, output
    assert sorted((project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db"))
    # Named, not a bare "3 records": the branches report that count too.
    assert f"✓ {JOINED} 3 records" in output, output
