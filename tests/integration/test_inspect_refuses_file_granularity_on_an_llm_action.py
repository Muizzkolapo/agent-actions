"""`agac inspect` and `agac run` refuse an LLM action at FILE granularity with one reason.

Inspect passed the config, and run refused it with `Configuration validation failed`
on its Problem line, the reason buried in a log line above. Both now print the reason
there. The HITL rule had the same split and is checked beside it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

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

_DEFAULTS = """\
defaults:
  json_mode: true
  run_mode: online
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
"""

LLM_AT_FILE = """\
actions:
  - name: label_page
    intent: "Label the page"
    granularity: File
    schema: { topic: string }
    prompt: $w.Label
    context_scope: { observe: [source.page_content] }
"""

LLM_UNDER_FILE_DEFAULTS = """\
  granularity: File
actions:
  - name: label_page
    intent: "Label the page"
    schema: { topic: string }
    prompt: $w.Label
    context_scope: { observe: [source.page_content] }
"""

HITL_AT_RECORD = """\
actions:
  - name: review
    kind: hitl
    intent: "Review the page"
    granularity: Record
    hitl: { port: 3999, instructions: "Review" }
    context_scope: { observe: [source.page_content] }
"""

LLM_REFUSAL = (
    "Problem: FILE granularity is only supported for tool and hitl actions. "
    "LLM actions must use RECORD granularity. "
    "Remove 'granularity: file' from the action, or make it a tool."
)
HITL_REFUSAL = "Problem: HITL actions require FILE granularity."
HIDDEN_REASON = "Configuration validation failed for 'agent_configuration'"


def _project(tmp_path: Path, actions: str) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / "w"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / "w.yml").write_text(
        f'name: w\ndescription: "Granularity"\nversion: "0.1.0"\n{_DEFAULTS}{actions}'
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / "w.md").write_text(
        "{prompt Label}\nLabel the page.\n{{ source.page_content }}\n{end_prompt}\n"
    )
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _traces(project: Path) -> int:
    (db,) = (project / "agent_workflow" / "w" / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute("select count(*) from prompt_trace").fetchone()[0]
    finally:
        con.close()


@pytest.mark.parametrize(
    ("actions", "refusal"),
    [(LLM_AT_FILE, LLM_REFUSAL), (HITL_AT_RECORD, HITL_REFUSAL)],
    ids=["llm_at_file", "hitl_at_record"],
)
@pytest.mark.parametrize("command", [("inspect",), ("run", "--fresh")], ids=["inspect", "run"])
def test_both_commands_refuse_with_the_reason_on_the_problem_line(
    tmp_path, actions, refusal, command
):
    project = _project(tmp_path, actions)

    result = run_agac(project, *command, "-a", "w")
    output = result.stdout + result.stderr

    assert result.returncode == 1, output
    assert refusal in output, output
    assert HIDDEN_REASON not in output, output
    assert "validate_agent_entries" not in output, output


def test_an_llm_action_under_file_defaults_runs_once_per_record(tmp_path):
    project = _project(tmp_path, LLM_UNDER_FILE_DEFAULTS)

    inspected = run_agac(project, "inspect", "action", "-a", "w", "label_page")
    ran = run_agac(project, "run", "-a", "w", "--fresh")

    assert inspected.returncode == 0, inspected.stdout + inspected.stderr
    granularity = [line for line in inspected.stdout.splitlines() if "Granularity" in line]
    assert [line.split() for line in granularity] == [["Granularity", "Record"]]
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert _traces(project) == len(PAGES)
