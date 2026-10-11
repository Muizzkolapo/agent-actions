"""A blank `output_field:` is refused at load, naming the key (1352).

Load accepted the blank key as None, expansion copied that None over the documented
default `raw_response`, and pre-flight was the first code to trip on it: the run exited 1
with "TypeError: '<' not supported between instances of 'str' and 'NoneType'", which
names no key. One LLM action over two staged rows, `json_mode: false`. Every command is
a real `agac run`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "blank_output_field"


def _config(defaults_line: str, action_line: str) -> str:
    return f"""\
name: {WORKFLOW}
description: "A blank output_field"
version: "0.1.0"
defaults:
  json_mode: false
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
{defaults_line}
actions:
  - name: say
    intent: "Say"
    prompt: "Say {{{{ source.text }}}}"
    context_scope: {{ observe: [source.text] }}
{action_line}
"""


def _project(
    base: Path, defaults_line: str = "", action_line: str = "", project_line: str = ""
) -> Path:
    root = base / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        "default_agent_config:\n  model_name: gpt-4o-mini\n" + project_line
    )
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_config(defaults_line, action_line))
    (workflow / "agent_io" / "staging" / "rows.json").write_text(
        json.dumps([{"text": "one"}, {"text": "two"}])
    )
    return root


def _run(root: Path):
    return run_agac(root, "run", "-a", WORKFLOW, "--fresh", env={"OPENAI_API_KEY": "sk-not-used"})


@pytest.mark.parametrize(
    "defaults_line, action_line, project_line",
    [
        pytest.param("  output_field:", "", "", id="defaults"),
        pytest.param("", "    output_field:", "", id="action"),
        pytest.param("", "", "  output_field:\n", id="project"),
    ],
)
def test_a_blank_output_field_is_refused_naming_the_key(
    tmp_path, defaults_line, action_line, project_line
):
    result = _run(_project(tmp_path, defaults_line, action_line, project_line))

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "output_field" in output, output
    assert "not supported between instances" not in output, output


def test_an_omitted_output_field_takes_the_default(tmp_path):
    result = _run(_project(tmp_path))

    assert result.returncode == 0, result.stdout + result.stderr
