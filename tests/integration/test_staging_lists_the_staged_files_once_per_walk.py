"""Staging lists the staged files once per walk, not once per staged file (1537).

Checking whether another staged file may hold a `source` field an action below the
first reads walked and stat-ed the whole staging folder for every staged file, before
any read was found missing: 800 files took twice as long to stage. The walk now lists
them once, and only when a read is missing.

Driven through `agac run` in-process, so the walks can be counted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.workflow import runner_file_processing

WORKFLOW = "staged_walks"
FILES = 6

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def staged_walks_echo(data: Any, *args) -> list[dict]:
    return [{"got": repr(data)}]
"""


def _project(root: Path, later_observe: str) -> None:
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    staging = directory / "agent_io" / "staging"
    staging.mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        'tool_path: ["tools"]\nschema_path: schema\n'
        "default_agent_config:\n  model_name: gpt-4o-mini\n"
    )
    (root / "tools" / WORKFLOW / "staged_walks_tools.py").write_text(TOOLS)
    (root / "schema" / WORKFLOW / "echo_out.yml").write_text(
        "name: echo_out\nfields:\n  - id: got\n    type: string\nadditionalProperties: true\n"
    )
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "Many staged files"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: first
    kind: tool
    intent: "Echo"
    impl: staged_walks_echo
    schema: echo_out
    context_scope: {{ observe: [source.*] }}
  - name: second
    kind: tool
    intent: "Echo again"
    impl: staged_walks_echo
    schema: echo_out
    dependencies: [first]
    context_scope: {{ observe: [first.got, {later_observe}] }}
"""
    )
    for n in range(FILES):
        (staging / f"part_{n}.json").write_text(json.dumps([{"title": f"t{n}"}]))


@pytest.fixture
def walks(monkeypatch):
    """Each walk of the staging folder, by the folder walked."""
    seen: list[str] = []
    real = runner_file_processing.walk_files

    def counting(root, on_error):
        if Path(root).name == "staging":
            seen.append(str(root))
        return real(root, on_error)

    monkeypatch.setattr(runner_file_processing, "walk_files", counting)
    return seen


@pytest.mark.parametrize(
    "later_observe", ["source.title", "source.body"], ids=["every-read-held", "a-read-missing"]
)
def test_the_staging_folder_is_not_walked_once_per_staged_file(
    tmp_path, monkeypatch, walks, later_observe
):
    _project(tmp_path, later_observe)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-used")

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

    assert "Step 1/2 first" in result.output, result.output
    missing = later_observe == "source.body"
    assert ("no record staged" in result.output) == missing, result.output
    # The run's own walks (the one that stages, the input fingerprint), never one a file.
    assert len(walks) <= 2, (len(walks), result.output)
