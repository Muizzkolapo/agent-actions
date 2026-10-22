"""``--verbose`` and ``--quiet`` beat ``logging.level`` in ``agent_actions.yml``.

The CLI configures logging twice (before Click parses the flags and again in the
group callback). The project block is the base for both; the flag must win in the
second, through the run's re-initialisation.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli

SOURCE = Path(__file__).parent.parent / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "tool_action"
PROGRESS_LINE = "Step 1/1 flatten"


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
    return root


def _set_level(root: Path, level: str) -> None:
    config = root / "agent_actions.yml"
    config.write_text(config.read_text().rstrip("\n") + f"\nlogging:\n  level: {level}\n")


def _run(*flags: str) -> str:
    result = CliRunner().invoke(cli, [*flags, "run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return result.output


def test_verbose_shows_progress_a_project_level_of_warning_would_hide(project):
    _set_level(project, "WARNING")

    assert PROGRESS_LINE not in _run()
    assert PROGRESS_LINE in _run("--verbose")


def test_quiet_hides_progress_a_project_level_of_info_would_show(project):
    _set_level(project, "INFO")

    assert PROGRESS_LINE in _run()
    assert PROGRESS_LINE not in _run("--quiet")
