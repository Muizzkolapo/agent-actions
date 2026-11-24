"""`-w` names the workflow in every command, against a store a real run wrote.

`run`, `retry`, `dispositions` and `status` took the workflow as `-a` alone, while
`traces`, `records` and `preview` took it as `-w` and read `-a` as the action. Now
`-a` names the workflow in every command and `-A` the action. Each
command here is a real `agac` process against a project in a tmp dir; the model is
the built-in fake provider.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "one_flag"
ACTION = "summarize"

CONFIG = f"""name: {WORKFLOW}
description: "a workflow every command is pointed at with -w"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: {ACTION}
    intent: "summarise each page"
    schema: page_summary
    prompt: $one_flag.Summarize
    context_scope: {{ observe: [source.page_content] }}
"""

PROMPTS = """{prompt Summarize}
Summarise the page in one sentence.
## PAGE
{{ source.page_content }}
```json
{"summary": "..."}
```
{end_prompt}
"""


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("one_flag")
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "agent_actions.yml").write_text(
        "default_agent_config:\n  api_key: OLLAMA_API_KEY\n  model_name: "
        "mock\nschema_path: schema\n"
    )
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(CONFIG)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_content": "Page alpha."}, {"page_content": "Page beta."}])
    )
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(PROMPTS)
    (root / "schema" / WORKFLOW / "page_summary.yml").write_text(
        "name: page_summary\nfields:\n  - id: summary\n    type: string\n"
    )
    result = run_agac(root, "run", "-w", WORKFLOW)
    assert result.returncode == 0, result.stdout + result.stderr
    return root


def test_run_w_workflow_runs_the_workflow(project):
    store = project / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.db"

    assert store.is_file()


def test_dispositions_w_workflow_shows_the_actions_counts(project):
    result = run_agac(project, "dispositions", "-w", WORKFLOW, env={"COLUMNS": "200"})

    assert result.returncode == 0, result.stdout + result.stderr
    row = next(line for line in result.stdout.splitlines() if f" {ACTION} " in line)
    assert [cell.strip() for cell in row.strip("│ ").split("│")][:2] == [ACTION, "2"]


@pytest.mark.parametrize("flag", ["--action", "-A"])
def test_traces_w_workflow_action_prints_the_prompts(project, flag):
    result = run_agac(project, "traces", "-w", WORKFLOW, flag, ACTION)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Page alpha." in result.stdout and "Page beta." in result.stdout
    assert "deprecated" not in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        ("status",),
        ("retry", "--dry-run"),
        ("inspect",),
        ("inspect", "action", ACTION),
        ("inspect", "context", ACTION),
        ("schema",),
        ("expect", "list"),
        ("expect", "report"),
        ("dispositions", "-A", ACTION),
        ("records",),
        ("preview",),
    ],
    ids=" ".join,
)
@pytest.mark.parametrize("flag", ["-w", "--workflow", "-a"])
def test_a_command_that_takes_a_workflow_takes_it_under_each_name(project, command, flag):
    result = run_agac(project, *command, flag, WORKFLOW)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("command", ["traces", "records", "preview"])
def test_a_names_the_workflow_and_capital_a_the_action(project, command):
    result = run_agac(project, command, "-a", WORKFLOW, "-A", ACTION)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Page alpha." in result.stdout or "summary" in result.stdout
    assert "deprecated" not in result.stdout + result.stderr


def test_records_a_workflow_prints_the_records(project):
    result = run_agac(project, "records", "-a", WORKFLOW)

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(json.loads(result.stdout)) == 2
    assert "deprecated" not in result.stderr


def test_a_command_given_no_workflow_names_every_way_to_give_one(project):
    result = run_agac(project, "status")

    assert result.returncode == 2
    assert "Error: Missing option '-w' / '--workflow' / '-a'." in result.stderr


@pytest.mark.parametrize("command", ["records", "preview"])
def test_records_and_preview_given_no_workflow_name_every_way_to_give_one(project, command):
    result = run_agac(project, command)

    assert result.returncode == 2
    assert "Error: Missing option '-w' / '--workflow' / '-a'." in result.stderr


def test_traces_given_no_action_names_the_option_it_lacks(project):
    result = run_agac(project, "traces", "-w", WORKFLOW)

    assert result.returncode == 2
    assert "Error: Missing option '-A' / '--action'." in result.stderr
