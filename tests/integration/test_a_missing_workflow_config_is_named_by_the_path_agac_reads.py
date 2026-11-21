"""`agac validate-udfs` on a workflow with no config file names the file it looked for."""

from __future__ import annotations

from pathlib import Path

import pytest

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
description: "One tool action"
version: "0.1.0"
defaults:
  json_mode: true
  run_mode: online
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: tag
    kind: tool
    intent: "Tag"
    impl: config_path_tag
    schema: { tag: string }
    context_scope: { observe: [source.page_id] }
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def config_path_tag(data: dict[str, Any]) -> dict[str, Any]:
    return {"tag": "t"}
"""


def _project(tmp_path: Path, workflows_dir: str) -> tuple[Path, Path]:
    """A project whose workflow `w` has its folders but no config file; returns (root, config)."""
    root = (tmp_path / "project").resolve()
    workflow = root / workflows_dir / "w"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (root / "tools" / "w").mkdir(parents=True)
    (root / "tools" / "w" / "config_path_tag.py").write_text(_TOOL)
    (root / "schema" / "w").mkdir(parents=True)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root, workflow / "agent_config" / "w.yml"


@pytest.mark.parametrize("workflows_dir", ["agent_workflow", "flows"])
def test_the_fix_names_the_config_file_agac_reads(tmp_path, workflows_dir):
    root, config = _project(tmp_path, workflows_dir)

    result = run_agac(root, "validate-udfs", "-a", "w", "-u", "tools")
    output = result.stdout + result.stderr

    assert result.returncode == 1, output
    assert "Agent configuration not found" in output, output
    assert f"Fix: 1. Create {config}\n" in output, output
    assert str(config).endswith(f"{workflows_dir}/w/agent_config/w.yml")


@pytest.mark.parametrize("workflows_dir", ["agent_workflow", "flows"])
def test_the_file_written_at_the_named_path_is_the_one_agac_reads(tmp_path, workflows_dir):
    root, config = _project(tmp_path, workflows_dir)
    config.write_text(_WORKFLOW)

    result = run_agac(root, "validate-udfs", "-a", "w", "-u", "tools")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "All UDF references valid" in output, output
