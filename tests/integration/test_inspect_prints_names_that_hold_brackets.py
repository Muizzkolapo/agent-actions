"""`agac inspect action` and `inspect context` print names that hold brackets as written.

An action name is the author's own string, and so are the fields a schema names; one
holding a closing tag raised MarkupError out of the consumers, input and context lines.
"""

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"
ODD = "sec[/b]"

EXTRA_ACTION = """  - name: "sec[/b]"
    dependencies: [summarize]
    intent: "Reads summarize"
    schema: batch_field_rules_output
    prompt: "Use {{ summarize.summary }}"
    context_scope: { observe: [summarize.summary, "summarize.[/x]"] }
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + EXTRA_ACTION)
    schema = root / "schema" / WORKFLOW / "batch_field_rules_output.yml"
    schema.write_text(
        schema.read_text().replace(
            "additionalProperties: true",
            '  - id: "[/x]"\n    type: string\nadditionalProperties: true',
        )
    )
    monkeypatch.chdir(root)
    monkeypatch.setenv("COLUMNS", "200")
    return root


def test_the_consumers_of_an_action_are_printed_as_written(project):
    result = CliRunner().invoke(cli, ["inspect", "action", "-a", WORKFLOW, "summarize"])

    assert result.exit_code == 0, result.output
    assert f"{ODD}  (depends on)" in result.output


def test_the_input_of_an_action_that_depends_on_one_with_brackets(project):
    """The same action read from the other side: its input names `summarize`, and the
    action under inspection is the odd one."""
    result = CliRunner().invoke(cli, ["inspect", "action", "-a", WORKFLOW, ODD])

    assert result.exit_code == 0, result.output
    assert "summarize" in result.output


def test_the_context_of_an_action_with_brackets_in_its_name(project):
    result = CliRunner().invoke(cli, ["inspect", "context", "-a", WORKFLOW, ODD])

    assert result.exit_code == 0, result.output
    assert "summarize" in result.output


def test_a_schema_field_with_a_closing_tag_is_printed_in_the_context(project):
    result = CliRunner().invoke(cli, ["inspect", "context", "-a", WORKFLOW, ODD])

    assert result.exit_code == 0, result.output
    assert "[/x]" in result.output
