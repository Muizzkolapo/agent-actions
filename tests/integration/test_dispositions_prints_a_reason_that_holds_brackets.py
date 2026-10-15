"""`agac dispositions --quarantined` prints a failure reason that holds brackets.

The stored reason of a failed record is the error text, which can quote record content
or a provider reply and so hold a closing tag. A Rich table cell parses markup, so such
a reason raised `MarkupError` and the command showed a traceback in place of the table.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "tool_action"

# A module and function of its own: tool discovery imports by module name, so a file that
# shares the fixture's `flatten.py` is served that module's cached import in a long run.
BREAKING_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def flat_brackets(data: Any, *args) -> list[dict]:
    text = str(((data or {}).get("source") or {}).get("page_content", ""))
    if text == "page 1":
        raise RuntimeError("[/note] gamma breaks")
    return [{"summary": text, "exam_density": "low"}]
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    (root / "tools" / WORKFLOW / "bracketed_flatten.py").write_text(BREAKING_TOOL)
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().replace("impl: flatten_pages", "impl: flat_brackets"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(
        json.dumps([{"page_content": f"page {i}"} for i in range(3)])
    )
    monkeypatch.chdir(root)
    monkeypatch.setenv("COLUMNS", "240")
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return root


def test_the_quarantined_table_prints_a_reason_with_a_closing_tag(project):
    result = CliRunner().invoke(cli, ["dispositions", "-a", WORKFLOW, "--quarantined"])

    assert result.exit_code == 0, result.output
    assert "[/note]" in result.output


def test_the_table_still_names_the_failed_record_and_its_action(project):
    """Control: the reason is the only cell whose text is free."""
    result = CliRunner().invoke(cli, ["dispositions", "-a", WORKFLOW, "--quarantined"])

    assert "flatten" in result.output
    assert "failed" in result.output
