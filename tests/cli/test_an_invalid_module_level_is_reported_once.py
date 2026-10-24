"""An invalid ``logging.module_levels`` entry is reported once per command, at boot.

The CLI initializes the logger factory twice per command and ``agac run`` once more
to attach its file handlers; the entry is validated when the project block is
resolved, so the report is not repeated on each init.
"""

import json
import logging
import shutil
from pathlib import Path

import pytest

from agent_actions.cli.main import CLI

SOURCE = Path(__file__).parent.parent / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "tool_action"
REPORT = "ignoring logging.module_levels['httpx']='LOUD':"

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
    for name in ("AGENT_ACTIONS_DEBUG", "AGENT_ACTIONS_LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    config = root / "agent_actions.yml"
    config.write_text(
        config.read_text().rstrip("\n")
        + "\nlogging:\n  module_levels:\n    httpx: LOUD\n    my_custom_lib: ERROR\n"
    )
    return root


@pytest.mark.parametrize(
    "argv",
    [["inspect", "-a", WORKFLOW], ["run", "-a", WORKFLOW, "--fresh"]],
    ids=["inspect", "run"],
)
def test_an_invalid_module_level_is_reported_once_per_command(project, capsys, argv):
    assert CLI().execute(argv) == 0

    assert capsys.readouterr().err.count(REPORT) == 1


def test_the_valid_entries_beside_it_still_apply(project):
    assert CLI().execute(["run", "-a", WORKFLOW, "--fresh"]) == 0

    assert logging.getLogger("my_custom_lib").level == logging.ERROR
    assert logging.getLogger("httpx").level == logging.WARNING
