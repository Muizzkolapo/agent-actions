"""`schema: dispatch_task('fn')` gives each record the schema its function picks.

Every record failed with `Schema file 'dispatch_task('fn')' not found`: the string was
filed as a schema name before the compiler that can resolve it saw it.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

PAGES = [
    {"page_id": "p1", "page_content": "alpha text"},
    {"page_id": "p2", "page_content": "beta text"},
]

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
tool_path: ["tools"]
schema_path: schema
"""

_WORKFLOW = """\
name: w
description: "A schema chosen per record"
version: "0.1.0"
defaults:
  json_mode: true
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: label_page
    intent: "Label the page"
    schema: dispatch_task('dsp_pick_schema')
    prompt: $w.Label
    context_scope: {{ observe: [source.page_id, source.page_content] }}
"""

_TOOL = """\
import json


def dsp_pick_schema(context_json):
    page_id = (json.loads(context_json).get("source") or {}).get("page_id", "")
    if page_id == "p1":
        return {"name": "topic_answer", "fields": [{"id": "topic", "type": "string"}]}
    return {"name": "verdict_answer", "fields": [{"id": "verdict", "type": "string"}]}
"""


def project(tmp_path: Path, run_mode: str = "online") -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / "w"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / "w.yml").write_text(_WORKFLOW.format(run_mode=run_mode))
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / "w.md").write_text(
        "{prompt Label}\nLabel the page.\n{{ source.page_content }}\n{end_prompt}\n"
    )
    (root / "tools" / "w").mkdir(parents=True)
    (root / "tools" / "w" / "dsp_pick_schema.py").write_text(_TOOL)
    (root / "schema").mkdir()
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def keys_by_page(root: Path) -> dict[str, set[str]]:
    backend = get_storage_backend(str(root / "agent_workflow" / "w"), "w")
    backend.initialize()
    try:
        rows = [
            row
            for path in backend.list_target_files("label_page")
            for row in backend.read_target("label_page", path)
        ]
    finally:
        backend.close()
    return {row["content"]["source"]["page_id"]: set(row["content"]["label_page"]) for row in rows}


def test_inspect_passes_it_without_looking_for_a_file(tmp_path):
    root = project(tmp_path)

    result = run_agac(root, "inspect", "-a", "w")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "Could not load schema" not in output, output
    assert "Schema loading failed" not in output, output


def test_each_record_answers_in_the_schema_its_function_picked(tmp_path):
    root = project(tmp_path)

    result = run_agac(root, "run", "-a", "w", "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    keys = keys_by_page(root)
    assert "topic" in keys["p1"] and "verdict" not in keys["p1"]
    assert "verdict" in keys["p2"] and "topic" not in keys["p2"]
