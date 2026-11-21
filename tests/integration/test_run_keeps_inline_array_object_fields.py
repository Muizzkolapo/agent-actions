"""`agac run` accepts an inline `array[object:{...}]` field and checks each item's fields."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tests._support.agac_cli import run_agac

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
tool_path: ["tools"]
schema_path: schema
"""

_WORKFLOW = """\
name: w
description: "Inline array of objects with named fields"
version: "0.1.0"
defaults:
  json_mode: true
  run_mode: online
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: pick
    kind: tool
    intent: "Pick rows"
    impl: pick_rows
    schema:
      rows: "array[object:{'q': 'string!', 'n': 'number'}]"
    context_scope: { observe: [source.page_id, source.page_content] }
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def pick_rows(data: dict[str, Any]) -> dict[str, Any]:
    if data["source"]["page_content"] == "bad":
        return {"rows": [{"n": 2}]}
    return {"rows": [{"q": "alpha", "n": 1}]}
"""


def _project(tmp_path: Path, pages: list[dict[str, str]]) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / "w"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / "w.yml").write_text(_WORKFLOW)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(pages))
    (root / "prompt_store").mkdir()
    (root / "schema" / "w").mkdir(parents=True)
    (root / "tools" / "w").mkdir(parents=True)
    (root / "tools" / "w" / "pick_rows.py").write_text(_TOOL)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _dispositions(root: Path) -> dict[str, str]:
    store = root / "agent_workflow" / "w" / "agent_io" / "store"
    (db,) = store.glob("*.db")
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "select record_id, disposition from record_disposition"
            " where action_name = 'pick' and record_id != '__node__'"
        ).fetchall()
    finally:
        con.close()
    return dict(rows)


def test_run_accepts_items_that_match_the_inline_object_fields(tmp_path):
    project = _project(
        tmp_path,
        [{"page_id": "p1", "page_content": "a"}, {"page_id": "p2", "page_content": "b"}],
    )

    result = run_agac(project, "run", "-a", "w", "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "object:" not in output, output
    dispositions = _dispositions(project)
    assert len(dispositions) == 2, dispositions
    assert set(dispositions.values()) == {"success"}, dispositions


def test_run_refuses_an_item_without_a_required_inline_object_field(tmp_path):
    project = _project(
        tmp_path,
        [{"page_id": "p1", "page_content": "a"}, {"page_id": "p2", "page_content": "bad"}],
    )

    result = run_agac(project, "run", "-a", "w", "--fresh")
    output = result.stdout + result.stderr

    dispositions = _dispositions(project)
    assert len(dispositions) == 2, output
    assert sorted(dispositions.values()).count("success") == 1, (dispositions, output)
