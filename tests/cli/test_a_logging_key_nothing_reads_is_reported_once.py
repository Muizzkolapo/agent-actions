"""A key under ``logging:`` that nothing reads is reported once per command, at boot.

The CLI configures logging twice per invocation (before Click parses the flags and
again in the group callback); the project block is resolved once so the report is
not doubled.
"""

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.cli.main import CLI

SOURCE = Path(__file__).parent.parent / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "tool_action"


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(json.dumps([{"page_content": "page"}]))
    monkeypatch.chdir(root)
    return root


def test_an_unread_logging_key_is_reported_once_per_command(project, capsys):
    config = project / "agent_actions.yml"
    config.write_text(config.read_text().rstrip("\n") + "\nlogging:\n  file:\n    path: run.log\n")

    assert CLI().execute(["inspect", "-a", WORKFLOW]) == 0

    err = capsys.readouterr().err
    assert err.count("ignoring logging.file.path:") == 1


def test_a_project_without_a_logging_block_reports_nothing(project, capsys):
    assert CLI().execute(["inspect", "-a", WORKFLOW]) == 0

    assert "ignoring logging" not in capsys.readouterr().err
