"""`agac list-udfs` shows each tool it discovers, as a table or as JSON."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.list_udfs import list_udfs_cmd
from agent_actions.utils.udf_management.registry import clear_registry

TOOLS = '''
from agent_actions import udf_tool


@udf_tool()
def shout(data):
    """Upper-case every value.

    Longer explanation that only the verbose listing keeps.
    """
    return data


@udf_tool()
def whisper(data):
    return data
'''


@pytest.fixture(autouse=True)
def _isolated_registry():
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
def tools(tmp_path: Path) -> Path:
    folder = tmp_path / "tools"
    folder.mkdir()
    (folder / "voices.py").write_text(TOOLS)
    return folder


def _invoke(*args: str):
    return CliRunner().invoke(list_udfs_cmd, list(args), terminal_width=200)


def test_the_table_names_each_tool_with_the_first_line_of_its_docstring(tools):
    result = _invoke("-u", str(tools))

    assert result.exit_code == 0, result.output
    assert "Discovered 2 Tools" in result.output
    assert "shout" in result.output
    assert "whisper" in result.output
    assert "Upper-case every value." in result.output
    assert "Longer explanation" not in result.output
    assert "Signature" not in result.output
    assert "Total: 2 function(s)" in result.output


def test_verbose_adds_the_signature_and_description_columns(tools):
    result = _invoke("-u", str(tools), "--verbose")

    assert result.exit_code == 0, result.output
    assert "Signature" in result.output
    assert "Description" in result.output
    assert "(data)" in result.output


def test_json_lists_each_tool_and_prints_nothing_else(tools):
    result = _invoke("-u", str(tools), "--json")

    assert result.exit_code == 0, result.output
    listing = json.loads(result.output)
    assert [entry["name"] for entry in listing] == ["shout", "whisper"]
    shout, whisper = listing
    assert shout["signature"] == "(data)"
    assert shout["file"].endswith("voices.py")
    assert shout["docstring"].startswith("Upper-case every value.")
    assert "docstring" not in whisper


def test_json_verbose_gives_every_tool_a_docstring_even_an_empty_one(tools):
    result = _invoke("-u", str(tools), "--json", "--verbose")

    listing = json.loads(result.output)
    assert listing[1]["name"] == "whisper"
    assert listing[1]["docstring"] == ""


def test_a_folder_without_tools_says_so(tmp_path):
    (tmp_path / "notes.py").write_text("x = 1\n")

    result = _invoke("-u", str(tmp_path))

    assert result.exit_code == 0, result.output
    assert "Discovered 0 Tools" in result.output
    assert "No UDFs found in the specified directory." in result.output


def test_a_folder_without_tools_is_an_empty_json_list(tmp_path):
    result = _invoke("-u", str(tmp_path), "--json")

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []


def test_a_missing_folder_is_a_usage_error(tmp_path):
    result = _invoke("-u", str(tmp_path / "gone"))

    assert result.exit_code == 2
    assert "does not exist" in result.output


def test_a_tool_file_that_does_not_import_fails_the_command(tmp_path):
    (tmp_path / "broken.py").write_text(
        "from agent_actions import udf_tool\nimport no_such_module_for_list_udfs\n\n\n"
        "@udf_tool()\ndef echo(data):\n    return data\n"
    )

    result = _invoke("-u", str(tmp_path), "--json")

    assert result.exit_code != 0
    assert "no_such_module_for_list_udfs" in result.output
