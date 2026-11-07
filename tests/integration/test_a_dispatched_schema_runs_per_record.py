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
    schema_options: [topic_answer, verdict_answer]
    prompt: $w.Label
    context_scope: {{ observe: [source.page_id, source.page_content] }}
"""

_TOOL = """\
import json


def dsp_pick_schema(context_json):
    page_id = (json.loads(context_json).get("source") or {}).get("page_id", "")
    return "topic_answer" if page_id == "p1" else "verdict_answer"
"""


def project(tmp_path: Path, run_mode: str = "online", tool: str | None = None) -> Path:
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
    (root / "tools" / "w" / "dsp_pick_schema.py").write_text(tool or _TOOL)
    (root / "schema").mkdir()
    for name, field in (("topic_answer", "topic"), ("verdict_answer", "verdict")):
        (root / "schema" / f"{name}.yml").write_text(
            f"name: {name}\nfields:\n  - id: {field}\n    type: string\n"
        )
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def keys_by_page(root: Path) -> dict[str, set[str] | None]:
    """The answer keys stored for each page; None for a record stored with no answer."""
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
    return {
        row["content"]["source"]["page_id"]: (
            None if row["content"]["label_page"] is None else set(row["content"]["label_page"])
        )
        for row in rows
    }


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


_NONE_FOR_P2 = """\
import json


def dsp_pick_schema(context_json):
    page_id = (json.loads(context_json).get("source") or {}).get("page_id", "")
    return "topic_answer" if page_id == "p1" else None
"""


def test_a_function_returning_none_fails_that_record_alone(tmp_path):
    root = project(tmp_path, tool=_NONE_FOR_P2)

    result = run_agac(root, "run", "-a", "w", "--fresh", env={"COLUMNS": "400"})
    output = result.stdout + result.stderr

    assert (
        "dispatch_task('dsp_pick_schema') in schema returned None, which is not in "
        "schema_options [topic_answer, verdict_answer]."
    ) in output, output
    assert "AttributeError" not in output, output
    assert keys_by_page(root) == {"p1": {"topic"}, "p2": None}


def test_a_dispatch_inside_a_named_schema_file_is_refused(tmp_path):
    """The render step inlines a named file before pre-flight, so its fields are checked too."""
    root = project(tmp_path)
    config = root / "agent_workflow" / "w" / "agent_config" / "w.yml"
    config.write_text(
        config.read_text()
        .replace("schema: dispatch_task('dsp_pick_schema')\n", "schema: field_dispatch\n")
        .replace("    schema_options: [topic_answer, verdict_answer]\n", "")
    )
    (root / "schema" / "field_dispatch.yml").write_text(
        "name: field_dispatch\nfields:\n  - id: topic\n    type: dispatch_task('dsp_pick_schema')\n"
    )

    result = run_agac(root, "inspect", "-a", "w", env={"COLUMNS": "400"})
    output = result.stdout + result.stderr

    assert result.returncode == 1, output
    assert "calls dispatch_task inside its schema fields" in output, output


def schemas_by_page(root: Path) -> dict[str, str | None]:
    """The schema each stored record names as the one that wrote it."""
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
    return {
        row["content"]["source"]["page_id"]: (row.get("metadata") or {}).get("output_schema")
        for row in rows
    }


def test_each_stored_record_names_the_schema_that_wrote_it(tmp_path):
    root = project(tmp_path)

    result = run_agac(root, "run", "-a", "w", "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert schemas_by_page(root) == {"p1": "topic_answer", "p2": "verdict_answer"}
