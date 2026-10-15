"""A model name and a schema field name print as written in `agac inspect action`.

The escape helper once put a backslash before every `]`, so `metrics[0]` printed as
`metrics[0\\]`; and a model name was interpolated into markup unescaped.
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
    config.write_text(
        config.read_text().replace("model_name: gpt-oss:120b-cloud", "model_name: m[/x]")
    )
    schema = root / "schema" / WORKFLOW / "batch_field_rules_output.yml"
    schema.write_text(
        schema.read_text().replace(
            "additionalProperties: true",
            '  - id: "metrics[0]"\n    type: string\nadditionalProperties: true',
        )
    )
    monkeypatch.chdir(root)
    monkeypatch.setenv("COLUMNS", "200")
    return root


def test_a_model_name_with_a_closing_tag_is_printed_as_written(project):
    result = CliRunner().invoke(cli, ["inspect", "action", "-a", WORKFLOW, "summarize"])

    assert result.exit_code == 0, result.output
    assert "m[/x]" in result.output


def test_a_field_name_with_a_bracket_pair_has_no_stray_backslash(project):
    result = CliRunner().invoke(cli, ["inspect", "action", "-a", WORKFLOW, "summarize"])

    assert "metrics[0]" in result.output
    assert "\\" not in result.output
