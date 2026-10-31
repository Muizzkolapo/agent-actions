"""A project file the CLI cannot read at boot is reported, and the defaults stand.

``--help``, ``--version`` and ``agac init`` never read the project file; a broken one
must not stop them. The commands that do read it fail on it on their own.
"""

import pytest

from agent_actions.cli.main import CLI


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path / "agent_actions.yml"


def test_invalid_yaml_is_reported_and_version_still_runs(project, capsys):
    project.write_text("schema_path: [unclosed\n")

    assert CLI().execute(["--version"]) == 0

    captured = capsys.readouterr()
    assert "Agent Actions CLI v" in captured.out
    assert "agent_actions: logging: not read from the project config" in captured.err
    assert "Invalid YAML in config file" in captured.err
    assert captured.err.count("not read from") == 1


def test_a_scalar_document_is_reported_and_help_still_runs(project, capsys):
    project.write_text("hello\n")

    assert CLI().execute(["--help"]) == 0

    captured = capsys.readouterr()
    assert "must be a mapping at the top level, got str" in captured.err
    assert "AttributeError" not in captured.err + captured.out


def test_a_project_that_loads_reports_nothing_at_boot(project, capsys):
    project.write_text("schema_path: schema\nlogging:\n  level: WARNING\n")

    assert CLI().execute(["--version"]) == 0

    assert "not read from" not in capsys.readouterr().err
