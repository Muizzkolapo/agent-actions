"""``agac run`` preflight warns when a tool reads the bus by an impl name (1609).

The bus is keyed by action name. A tool reading ``data.get("<impl>")`` gets an empty dict and
says nothing, so the mistake surfaced actions later. ``validate-udfs`` already warned; a run
did not. Each run is an ``agac run``.
"""

import json
import shutil
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "bus_keys"

CONFIG = """name: bus_keys
description: "a reader names its upstream by impl"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: compile_input
    kind: tool
    impl: m_compile_input
    intent: "Compile"
    schema: { sig: string }
    context_scope: { observe: [source.page_id] }
  - name: verify
    kind: tool
    impl: m_verify
    dependencies: [compile_input]
    intent: "Verify"
    schema: { ok: string }
    context_scope: { observe: [compile_input.sig] }
"""

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool()
def m_compile_input(data: dict[str, Any]) -> dict[str, Any]:
    return {{"sig": "s"}}


@udf_tool()
def m_verify(data: dict[str, Any]) -> dict[str, Any]:
    return {{"ok": str(data.get({key!r}, {{}}).get("sig"))}}
"""


def _run(tmp_path, key):
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
    (root / "tools" / WORKFLOW / "keys.py").write_text(TOOLS.format(key=key))
    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")
    assert result.returncode == 0, result.stdout + result.stderr
    return " ".join((result.stdout + result.stderr).split())


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


def test_a_read_by_impl_name_is_warned_before_the_run(tmp_path):
    output = _run(tmp_path, "m_compile_input")

    assert "Pre-flight: bus namespaces — 1 warning(s)" in output
    assert "m_verify: reads bus namespace 'm_compile_input' which is not an action name" in output
    assert output.index("bus namespaces") < output.index("Step 1/2")


def test_a_read_by_action_name_is_not(tmp_path):
    output = _run(tmp_path, "compile_input")

    assert "bus namespaces" not in output
