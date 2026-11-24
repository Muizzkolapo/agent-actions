"""A command that reads a workflow's store creates none when the workflow has not run.

Opening the store to read it would leave an empty `agent_io/store/<workflow>.db` behind.
Each command says there is no store instead, and so does a retry that writes. Under
`--sandbox` the store is `<workflow>.sandbox.db`, so a real store does not count.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli import dispositions as dispositions_command
from agent_actions.cli.main import cli
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

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


def test_dispositions_json_on_a_workflow_never_run_prints_nothing_on_stdout(never_run):
    result = CliRunner().invoke(cli, ["dispositions", "-w", WORKFLOW, "--json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert f"No store for workflow '{WORKFLOW}'" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["retry"], id="retry"),
        pytest.param(["retry", "--all"], id="retry-all"),
        pytest.param(["retry", "--filter", "summarize:r1", "--reason", "r"], id="retry-filter"),
    ],
)
def test_a_retry_that_writes_refuses_a_workflow_never_run_and_creates_no_store(never_run, args):
    result = CliRunner().invoke(cli, [*args[:1], "-w", WORKFLOW, *args[1:]])

    assert result.exit_code == 1, result.output
    assert f"No store for workflow '{WORKFLOW}'" in result.output
    assert not never_run.parent.exists()


def _make_store(path: Path) -> None:
    backend = SQLiteBackend(str(path), WORKFLOW)
    backend.initialize()
    backend.close()


SANDBOX_READS = [
    pytest.param(["dispositions", "--sandbox"], id="dispositions"),
    pytest.param(["dispositions", "--sandbox", "--json"], id="dispositions-json"),
    pytest.param(["retry", "--sandbox", "--dry-run"], id="retry-dry-run"),
]


@pytest.mark.parametrize("args", SANDBOX_READS)
def test_a_sandbox_read_reads_the_sandbox_store_when_no_real_one_exists(never_run, args):
    sandbox_store = never_run.with_name(f"{WORKFLOW}.sandbox.db")
    _make_store(sandbox_store)

    result = CliRunner().invoke(cli, [*args[:1], "-w", WORKFLOW, *args[1:]])

    assert result.exit_code == 0, result.output
    assert "No store for workflow" not in result.output
    assert not never_run.exists()


@pytest.mark.parametrize(
    "args",
    [
        *SANDBOX_READS,
        pytest.param(["retry", "--sandbox"], id="retry"),
        pytest.param(
            ["retry", "--sandbox", "--filter", "summarize:r1", "--reason", "r"],
            id="retry-filter",
        ),
    ],
)
def test_a_sandbox_read_refuses_when_only_a_real_store_exists(never_run, args):
    _make_store(never_run)
    sandbox_store = never_run.with_name(f"{WORKFLOW}.sandbox.db")

    result = CliRunner().invoke(cli, [*args[:1], "-w", WORKFLOW, *args[1:]])

    assert result.exit_code == 1, result.output
    assert f"No store for workflow '{WORKFLOW}'" in result.output
    assert sandbox_store.name in result.output
    assert not sandbox_store.exists()


def test_dispositions_reads_through_a_connection_that_refuses_writes(never_run, monkeypatch):
    _make_store(never_run)
    write_refused = []
    real_report = dispositions_command.dispositions_report

    def report_after_a_write(backend, *args):
        try:
            backend.connection.execute("CREATE TABLE probe (x)")
        except sqlite3.OperationalError as error:
            write_refused.append("readonly" in str(error))
        else:
            write_refused.append(False)
        return real_report(backend, *args)

    monkeypatch.setattr(dispositions_command, "dispositions_report", report_after_a_write)

    result = CliRunner().invoke(cli, ["dispositions", "-w", WORKFLOW, "--json"])

    assert result.exit_code == 0, result.output
    assert write_refused == [True]
