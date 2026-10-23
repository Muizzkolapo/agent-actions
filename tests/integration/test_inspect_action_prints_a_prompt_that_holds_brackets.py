"""`agac inspect action` prints a prompt or guard that holds brackets as written.

Llama-style prompts carry `[INST]` and `[/INST]`, and a guard can compare a field to a
string holding one. Printed through Rich markup, the closing tag raised `MarkupError`
and the command showed a traceback in place of the action.
"""

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    text = config.read_text()
    text = text.replace(
        "    prompt: $p.Summarize\n",
        "    prompt: |\n"
        "      [INST] Summarize {{ source.page_content }} [/INST]\n"
        "    guard: { condition: 'source.page_content != \"[/note]\"', on_false: skip }\n",
    )
    config.write_text(text)
    monkeypatch.chdir(root)
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    return root


def test_the_prompt_is_printed_as_written(project):
    result = CliRunner().invoke(cli, ["inspect", "action", "-a", WORKFLOW, "summarize"])

    assert result.exit_code == 0, result.output
    assert "[INST] Summarize {{ source.page_content }} [/INST]" in result.output


def test_the_guard_clause_is_printed_as_written(project):
    result = CliRunner().invoke(cli, ["inspect", "action", "-a", WORKFLOW, "summarize"])

    assert 'source.page_content != "[/note]"' in result.output
