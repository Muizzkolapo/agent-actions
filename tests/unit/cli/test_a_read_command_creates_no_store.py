"""A command that reads a workflow's store creates none when the workflow has not run.

Opening the store to read it would leave an empty `agent_io/store/<workflow>.db` behind.
Each command says there is no store instead.
"""

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli

FIXTURE = Path(__file__).resolve().parents[2] / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"


@pytest.fixture
def never_run(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs", "store"))
    monkeypatch.chdir(root)
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    return root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.db"


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["dispositions"], id="dispositions"),
        pytest.param(["dispositions", "--json"], id="dispositions-json"),
        pytest.param(["dispositions", "--quarantined"], id="dispositions-quarantined"),
        pytest.param(["retry", "--dry-run"], id="retry-dry-run"),
        pytest.param(
            ["retry", "--filter", "summarize:r1", "--reason", "r", "--dry-run"],
            id="retry-filter-dry-run",
        ),
        pytest.param(["records"], id="records"),
        pytest.param(["traces", "-A", "summarize"], id="traces"),
        pytest.param(["usage"], id="usage"),
    ],
)
def test_a_read_command_says_there_is_no_store_and_creates_none(never_run, args):
    result = CliRunner().invoke(cli, [*args[:1], "-w", WORKFLOW, *args[1:]])

    assert result.exit_code != 0
    assert f"No store for workflow '{WORKFLOW}'" in result.output
    assert not never_run.exists()


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["preview"], id="preview"),
        pytest.param(["expect", "report"], id="expect-report"),
        pytest.param(["status"], id="status"),
    ],
)
def test_a_read_command_that_reports_nothing_run_creates_no_store(never_run, args):
    result = CliRunner().invoke(cli, [*args, "-w", WORKFLOW])

    assert result.exit_code == 0, result.output
    assert not never_run.exists()
