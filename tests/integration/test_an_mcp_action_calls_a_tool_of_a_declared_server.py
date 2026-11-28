"""A `kind: mcp` action calls a tool of an MCP server the project declares, once a record.

The server is a fake started over stdio. A real run calls it with each record's
arguments; a tool error fails the record; a sandbox run answers from the schema and
starts no server unless the scenario sets `stub: false`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests._support.agac_cli import REPO, run_agac

WORKFLOW = "w"
SERVER = REPO / "tests" / "_support" / "fake_mcp_server.py"
PAGES = [{"page_id": "p1"}, {"page_id": "p2"}]

_PROJECT = f"""\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
tool_path: ["tools"]
schema_path: schema
mcp_servers:
  fake:
    command: {json.dumps(sys.executable)}
    args: [{json.dumps(str(SERVER))}]
    env: {{ FAKE_MCP_LOG: "${{FAKE_MCP_LOG}}" }}
"""

_WORKFLOW = """\
name: w
description: "An MCP tool, once a record"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: owner
    kind: mcp
    server: {server}
    tool: {tool}
    intent: "Find the owner of each ticket"
    schema: owner_out
    arguments:
      ticket: source.page_id
      tier: {{ value: gold }}
"""

_SCHEMA = """\
name: owner_out
fields:
  - id: owner
    type: string
  - id: tier
    type: string
"""


def _project(tmp_path: Path, server: str = "fake", tool: str = "lookup") -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _WORKFLOW.format(server=server, tool=tool)
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text("")
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "owner_out.yml").write_text(_SCHEMA)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


@pytest.fixture
def log(tmp_path: Path) -> Path:
    return tmp_path / "calls.jsonl"


def _agac(root: Path, log: Path, *args: str):
    return run_agac(root, *args, env={"FAKE_MCP_LOG": str(log)})


def _calls(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def _stored(root: Path, log: Path, *flags: str) -> list[dict]:
    shown = _agac(root, log, "records", "-w", WORKFLOW, "-A", "owner", *flags)
    assert shown.returncode == 0, shown.stdout + shown.stderr
    return [record["content"]["owner"] for record in json.loads(shown.stdout)]


def test_a_run_calls_the_tool_with_each_record_s_arguments(tmp_path, log):
    root = _project(tmp_path)

    ran = _agac(root, log, "run", "-w", WORKFLOW)

    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert sorted(_calls(log), key=lambda c: c["arguments"]["ticket"]) == [
        {"tool": "lookup", "arguments": {"ticket": "p1", "tier": "gold"}},
        {"tool": "lookup", "arguments": {"ticket": "p2", "tier": "gold"}},
    ]
    assert sorted(o["owner"] for o in _stored(root, log)) == ["team-p1", "team-p2"]


def test_a_tool_error_fails_the_record_with_the_server_s_message(tmp_path, log):
    root = _project(tmp_path, tool="broken")

    ran = _agac(root, log, "run", "-w", WORKFLOW)

    # Every record failed, so the action failed, as with a UDF that raises.
    said = " ".join((ran.stdout + ran.stderr).split())
    assert ran.returncode == 1, said
    assert "Tool 'broken' of MCP server 'fake' failed: the lookup is down" in said
    assert len(_calls(log)) == 2


def test_a_server_the_project_does_not_declare_is_refused_before_the_run(tmp_path, log):
    root = _project(tmp_path, server="dbt")

    ran = _agac(root, log, "run", "-w", WORKFLOW)

    said = " ".join((ran.stdout + ran.stderr).split())
    assert ran.returncode != 0
    assert "no MCP server named 'dbt' in agent_actions.yml (declared: fake)" in said
    assert _calls(log) == []


def test_a_sandbox_run_answers_from_the_schema_and_starts_no_server(tmp_path, log):
    root = _project(tmp_path)

    ran = _agac(root, log, "run", "-w", WORKFLOW, "--sandbox")

    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert _calls(log) == []
    assert all(set(o) >= {"owner", "tier"} for o in _stored(root, log, "--sandbox"))


def test_a_scenario_that_sets_stub_false_calls_the_server_in_the_sandbox(tmp_path, log):
    root = _project(tmp_path)
    (root / "sandbox.yml").write_text("actions:\n  owner:\n    stub: false\n")

    ran = _agac(root, log, "run", "-w", WORKFLOW, "--sandbox")

    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert len(_calls(log)) == 2
