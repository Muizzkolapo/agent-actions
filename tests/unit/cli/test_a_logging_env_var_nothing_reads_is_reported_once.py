"""An ``AGENT_ACTIONS_*`` logging variable that nothing reads is reported once per command.

The run log always goes to ``<output_dir>/logs/events.json`` at DEBUG, so a variable
that claims to move, disable, re-level or re-format it configures nothing.
"""

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.cli.main import CLI

SOURCE = Path(__file__).parents[2] / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "tool_action"

UNREAD = (
    "AGENT_ACTIONS_LOG_FILE",
    "AGENT_ACTIONS_LOG_DIR",
    "AGENT_ACTIONS_NO_LOG_FILE",
    "AGENT_ACTIONS_FILE_LOG_LEVEL",
    "AGENT_ACTIONS_LOG_FORMAT",
)

pytestmark = pytest.mark.usefixtures("isolated_user_tools")


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(json.dumps([{"page_content": "page"}]))
    monkeypatch.chdir(root)
    for name in UNREAD:
        monkeypatch.delenv(name, raising=False)
    return root


@pytest.mark.parametrize("name", UNREAD)
def test_an_unread_logging_env_var_is_reported_once_per_command(project, monkeypatch, capsys, name):
    monkeypatch.setenv(name, "1")

    assert CLI().execute(["inspect", "-a", WORKFLOW]) == 0

    assert capsys.readouterr().err.count(f"ignoring {name}:") == 1


def test_a_read_logging_env_var_is_not_reported(project, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_ACTIONS_LOG_RETAIN_RUNS", "2")
    monkeypatch.setenv("AGENT_ACTIONS_LOG_DIR", "elsewhere")

    assert CLI().execute(["inspect", "-a", WORKFLOW]) == 0

    err = capsys.readouterr().err
    assert "ignoring AGENT_ACTIONS_LOG_DIR:" in err
    assert "AGENT_ACTIONS_LOG_RETAIN_RUNS" not in err
