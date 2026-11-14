"""`agac inspect` refuses `anthropic_version` by name wherever an action's settings are written."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

REASON = (
    "'anthropic_version' is no longer read and configures nothing; remove it"
    " — the Anthropic SDK sets the API version"
)

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
{project_key}"""

_WORKFLOW = """\
name: w
description: "One action"
version: "0.1.0"
defaults:
  run_mode: online
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
{defaults_key}actions:
  - name: summarize
    intent: "Summarise"
    schema: {{ summary: string }}
    prompt: $w.Summarize
    context_scope: {{ observe: [source.page_content] }}
{action_key}"""

_PROMPTS = """\
{prompt Summarize}
Summarise.
{{ source.page_content }}
{end_prompt}
"""


def _project(tmp_path: Path, level: str | None) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / "w"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / "w.yml").write_text(
        _WORKFLOW.format(
            defaults_key='  anthropic_version: "2023-06-01"\n' if level == "defaults" else "",
            action_key='    anthropic_version: "2023-06-01"\n' if level == "action" else "",
        )
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        '[{"page_id": "p1", "page_content": "alpha"}]'
    )
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / "w.md").write_text(_PROMPTS)
    (root / "agent_actions.yml").write_text(
        _PROJECT.format(
            project_key='  anthropic_version: "2023-06-01"\n' if level == "project" else ""
        )
    )
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


@pytest.mark.parametrize(
    "level,where",
    [
        ("action", "action 'summarize': "),
        ("defaults", "defaults: "),
        ("project", "default_agent_config: "),
    ],
)
def test_inspect_refuses_the_key_by_name(tmp_path, level, where):
    result = run_agac(_project(tmp_path, level), "inspect", "-a", "w")
    output = result.stdout + result.stderr

    assert result.returncode == 1, output
    assert where + REASON in output, output


def test_the_same_workflow_without_the_key_loads(tmp_path):
    result = run_agac(_project(tmp_path, None), "inspect", "-a", "w")

    assert result.returncode == 0, result.stdout + result.stderr
