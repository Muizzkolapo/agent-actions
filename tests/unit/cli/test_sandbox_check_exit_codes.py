"""`agac sandbox check` exits 0, 1, 2 or 130, and never with the code of a mismatch by accident.

0 every value holds; 1 a value does not hold or the run wrote no result; 2 the file is not
valid or the check could not run (an unexpected exception: one line, no traceback); 130 on
Ctrl-C. The run is replaced here by a stand-in that writes a status file, as a run that
loads the workflow does, and then ends as each test says.
"""

from __future__ import annotations

import json
import signal
import sqlite3
from pathlib import Path

import pytest

from agent_actions.cli.main import CLI
from agent_actions.cli.run import RunCommand

WORKFLOW = "wf"
STATUS = {"classify": {"status": "completed"}}


@pytest.fixture(autouse=True)
def _keep_signal_handlers():
    """CLI() installs its own SIGINT and SIGTERM handlers; put pytest's back."""
    held = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    yield
    for sig, handler in held.items():
        signal.signal(sig, handler)


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "project"
    (root / "agent_workflow" / WORKFLOW / "agent_config").mkdir(parents=True)
    (root / "agent_workflow" / WORKFLOW / "agent_io" / "staging").mkdir(parents=True)
    (root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"name: {WORKFLOW}\n"
    )
    (root / "agent_actions.yml").write_text("project_name: project\n")
    (root / "sandbox_expected.yml").write_text(
        "exit_code: 0\nactions:\n  classify: {status: completed}\n"
    )
    monkeypatch.chdir(root)
    return root


def _run_ends(
    monkeypatch,
    project: Path,
    end: BaseException | None,
    *,
    writes: bool = True,
    written_before_the_lock: bool = False,
) -> None:
    """Stand in for the run: inside *holding_the_lock*, write the status file, then end with *end*.

    *written_before_the_lock* writes it first, as another run that ends before this run
    takes the lock does.
    """

    def execute(self, project_root=None, holding_the_lock=None):
        status = project / "agent_workflow" / WORKFLOW / "agent_io" / "sandbox"
        status.mkdir(parents=True, exist_ok=True)
        if written_before_the_lock:
            (status / ".agent_status.json").write_text(json.dumps(STATUS))
        with holding_the_lock():
            if writes:
                (status / ".agent_status.json").write_text(json.dumps(STATUS))
            if end is not None:
                raise end

    monkeypatch.setattr(RunCommand, "execute", execute)


def _check() -> int | str | None:
    """The exit code of the command: a SystemExit it raises leaves `CLI.execute` as it is."""
    try:
        return CLI().execute(["sandbox", "check", "-w", WORKFLOW])
    except SystemExit as stop:
        return stop.code


def test_a_run_that_ends_normally_and_holds_every_value_exits_0(project, monkeypatch, capsys):
    _run_ends(monkeypatch, project, None)

    assert _check() == 0
    assert "PASS: all 2 expectations hold." in capsys.readouterr().out


def test_a_run_that_exits_with_no_code_is_exit_code_0(project, monkeypatch, capsys):
    _run_ends(monkeypatch, project, SystemExit(None))

    assert _check() == 0
    assert "✓ exit code" in capsys.readouterr().out


def test_a_run_exit_code_that_differs_from_the_file_exits_1(project, monkeypatch, capsys):
    _run_ends(monkeypatch, project, SystemExit(3))

    assert _check() == 1
    assert "exit code: expected 0, got 3" in capsys.readouterr().out


def test_an_unexpected_exception_exits_2_with_one_line_and_no_traceback(
    project, monkeypatch, capsys
):
    _run_ends(monkeypatch, project, RuntimeError("the store broke"))

    assert _check() == 2
    captured = capsys.readouterr()
    assert "Error: sandbox check could not run: RuntimeError: the store broke" in captured.err
    assert "Traceback" not in captured.out + captured.err
    assert "PASS" not in captured.out
    assert "FAIL" not in captured.out


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(130)], ids=repr)
def test_ctrl_c_exits_130(project, monkeypatch, capsys, interrupt):
    _run_ends(monkeypatch, project, interrupt)

    assert _check() == 130
    assert "PASS" not in capsys.readouterr().out


def test_a_status_file_written_before_the_run_took_the_lock_is_not_its_result(
    project, monkeypatch, capsys
):
    _run_ends(monkeypatch, project, None, writes=False, written_before_the_lock=True)

    assert _check() == 1
    out = capsys.readouterr().out
    assert "wrote no result" in out
    assert "PASS" not in out


def _reading_fails(monkeypatch) -> None:
    def read_output(io_dir, workflow):
        raise sqlite3.OperationalError("no such table: dispositions")

    monkeypatch.setattr("agent_actions.cli.sandbox_check.read_output", read_output)


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(130)], ids=repr)
def test_ctrl_c_exits_130_when_the_output_cannot_be_read(project, monkeypatch, interrupt):
    _run_ends(monkeypatch, project, interrupt)
    _reading_fails(monkeypatch)

    assert _check() == 130


def test_output_that_cannot_be_read_after_a_run_that_ended_exits_2(project, monkeypatch, capsys):
    _run_ends(monkeypatch, project, None)
    _reading_fails(monkeypatch)

    assert _check() == 2
    assert "could not run: OperationalError" in capsys.readouterr().err


def test_outside_a_project_the_check_could_not_run_and_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert _check() == 2
    assert "Project not found" in capsys.readouterr().err
