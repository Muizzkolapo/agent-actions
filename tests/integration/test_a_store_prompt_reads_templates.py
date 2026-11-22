"""A prompt-store prompt reads the macros and variables of templates/ as a prompt written in
the workflow file does, in either run mode.

templates.md "What Renders When": a prompt's own `{{ }}` tag that reads only load-time names
renders at load, and a macro used beside a per-record name fails the load naming the prompt.
A store prompt (`prompt: $file.Prompt`) failed every record on the templates/ name instead.
Driven through `agac run` against the agac provider mock; what each record was sent is read
back from the action's prompt traces.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_actions.cli.exit_codes import EXIT_PAUSED
from tests._support.agac_cli import run_agac
from tests.helpers.trace_store import trace_rows

WORKFLOW = "store_templates"
PAGES = [
    {"page_id": "p0", "page_content": "Photosynthesis turns light into sugar."},
    {"page_id": "p1", "page_content": "Volcanoes vent molten rock."},
]
MODES = ["online", "batch"]

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: gpt-oss:120b-cloud
tool_path: ["tools"]
schema_path: schema
seed_data_path: seed_data
"""

_WORKFLOW = """\
name: store_templates
description: "Store prompts that read templates/"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {mode}
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: describe
    intent: "Describe the page"
    prompt: $style.Describe
    schema: {{answer: string}}
    context_scope: {{ observe: [source.page_id, source.page_content] }}
"""

_TEMPLATES = """\
{% set tone = "warm" %}
{% macro voice(kind) %}Speak in a {{ kind }} tone.{% endmacro %}
"""


def _project(tmp_path: Path, mode: str, prompt: str) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_WORKFLOW.format(mode=mode))
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    for folder in ("templates", "schema", "seed_data", "prompt_store", "tools"):
        (root / folder).mkdir()
    (root / "templates" / "style.j2").write_text(_TEMPLATES)
    (root / "prompt_store" / "style.md").write_text(
        f"{{prompt Describe}}\n{prompt}\n{{end_prompt}}\n"
    )
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run(project: Path) -> tuple[int, str]:
    """`agac run --fresh`, then `agac run` while a batch is left to collect."""
    outputs = []
    args = ["run", "-a", WORKFLOW, "--fresh"]
    for _ in range(4):
        result = run_agac(project, *args, env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"})
        output = result.stdout + result.stderr
        outputs.append(output)
        if result.returncode != EXIT_PAUSED:
            return result.returncode, " ".join("\n".join(outputs).split())
        args = ["run", "-a", WORKFLOW]
    pytest.fail("the workflow never stopped asking to be run again:\n" + "\n".join(outputs))


def _prompts(project: Path) -> list[str]:
    rows = trace_rows(
        project,
        "select compiled_prompt from prompt_trace where action_name = 'describe' and attempt = 0",
    )
    return sorted(prompt for (prompt,) in rows)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("prompt", "sent"),
    [
        pytest.param(
            "Use a {{ tone }} voice: {{ source.page_content }}",
            "Use a warm voice: {}",
            id="variable",
        ),
        pytest.param(
            "{{ voice('calm') }} {{ source.page_content }}",
            "Speak in a calm tone. {}",
            id="macro",
        ),
    ],
)
def test_a_store_prompt_sends_each_record_what_templates_gives_it(tmp_path, mode, prompt, sent):
    project = _project(tmp_path, mode, prompt)

    code, output = _run(project)

    assert code == 0, output
    assert _prompts(project) == sorted(sent.format(page["page_content"]) for page in PAGES)


def test_a_store_prompt_using_a_macro_beside_a_record_name_fails_the_load_naming_it(tmp_path):
    project = _project(tmp_path, "online", "{{ voice(source.page_id) }} {{ source.page_content }}")

    code, output = _run(project)

    assert code != 0
    assert (
        "The prompt at line 1 of store prompt style.Describe reads 'source', so it renders for "
        "each record, but it also uses 'voice', a macro of the load"
    ) in output
    assert "references undefined variables" not in output
