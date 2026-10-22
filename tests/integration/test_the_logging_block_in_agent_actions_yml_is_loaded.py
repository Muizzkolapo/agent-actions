"""The ``logging:`` block in ``agent_actions.yml`` configures the run's logging.

``level`` sets the console level and ``module_levels`` re-opens a logger the
framework clamps. Both must still hold after ``agac run`` re-initialises the
factory to attach the run's file handlers, not only at CLI boot.
"""

import json
import logging
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "tool_action"
PROGRESS_LINE = "Step 1/1 flatten"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A tool-only project at cwd; the test appends its own ``logging:`` block."""
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(
        json.dumps([{"page_content": f"page {i}"} for i in range(3)])
    )
    monkeypatch.chdir(root)
    for name in ("AGENT_ACTIONS_DEBUG", "AGENT_ACTIONS_LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    return root


def _add_logging_block(root: Path, block: str) -> None:
    config = root / "agent_actions.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + block + "\n")


def _run(root: Path) -> str:
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return result.output


def test_without_a_logging_block_the_run_prints_progress_and_clamps_httpx(project):
    output = _run(project)

    assert PROGRESS_LINE in output
    assert logging.getLogger("httpx").level == logging.WARNING


def test_logging_level_in_the_project_config_sets_the_console_level(project):
    _add_logging_block(project, "logging:\n  level: WARNING")

    output = _run(project)

    assert PROGRESS_LINE not in output


def test_module_levels_in_the_project_config_survive_the_run_reinit(project):
    _add_logging_block(project, "logging:\n  module_levels:\n    httpx: INFO")

    _run(project)

    assert logging.getLogger("httpx").level == logging.INFO
