"""A tool's failure names the exception type as well as its message (1607).

A ``KeyError`` says only the key, ``'no_such_namespace'``, which reads as noise without
its type. Each run is an ``agac run``.
"""

import json
import shutil
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "names_the_type"

CONFIG = """name: names_the_type
description: "a tool that raises"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: lookup
    kind: tool
    impl: names_the_type_lookup
    intent: "Look up"
    schema: { found: string }
    context_scope: { observe: [source.page_id] }
"""

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool()
def names_the_type_lookup(data: dict[str, Any]) -> dict[str, Any]:
    return {"found": {}["no_such_namespace"]}
"""


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


def test_a_key_error_is_named_as_one(tmp_path):
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
    (root / "tools" / WORKFLOW / "lookup.py").write_text(TOOLS)

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode != 0
    assert "Error executing UDF 'names_the_type_lookup': KeyError: 'no_such_namespace'" in output
