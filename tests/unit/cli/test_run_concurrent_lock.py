"""Regression tests for VIOL-0045: `agac run` acquires an advisory file lock so
a second concurrent run against the same workflow store cannot silently
double-execute. `--force` bypasses the lock.

These drive the `run` Click command in-process (CliRunner) with the actual
workflow execution mocked out, so they exercise the real lock-acquisition
wiring without needing an LLM or a full project workflow. The contended lock is
held via a raw `fcntl.flock` on a *separate* open file description — POSIX
treats that as a distinct holder even within the same process, so the command's
own acquire attempt is denied exactly as a second `agac run` process would be.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from agent_actions.cli.run import run


def _make_project(root: Path) -> Path:
    (root / "agent_actions.yml").write_text("name: test_project\n", encoding="utf-8")
    store_dir = root / "agent_io" / "store"
    store_dir.mkdir(parents=True, exist_ok=True)
    return store_dir


def _lock_path(store_dir: Path, workflow_name: str) -> Path:
    return store_dir / f"{workflow_name}.db.lock"


def _hold_lock(lock_path: Path) -> int:
    """Hold an exclusive non-blocking flock on the lock file, stamping our pid
    into the body the way a live run would. Returns the fd; caller closes it."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.write(fd, str(os.getpid()).encode("utf-8"))
    os.fsync(fd)
    return fd


@pytest.fixture()
def project(tmp_path, monkeypatch):
    store_dir = _make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path, store_dir


def test_second_concurrent_run_exits_with_lock_message(project):
    _, store_dir = project
    fd = _hold_lock(_lock_path(store_dir, "lock_smoke"))
    try:
        with patch("agent_actions.cli.run.RunCommand.execute") as mock_exec:
            result = CliRunner().invoke(run, ["-a", "lock_smoke"])
    finally:
        os.close(fd)

    assert mock_exec.call_count == 0, "workflow must not execute while lock is held"
    assert result.exit_code == 1, result.output
    combined = result.output.lower()
    assert "another" in combined
    assert "agac run" in combined
    assert "pid" in combined
    assert "--force" in combined


def test_force_bypasses_the_lock(project):
    _, store_dir = project
    fd = _hold_lock(_lock_path(store_dir, "lock_smoke"))
    try:
        with patch("agent_actions.cli.run.RunCommand.execute") as mock_exec:
            result = CliRunner().invoke(run, ["-a", "lock_smoke", "--force"])
    finally:
        os.close(fd)

    assert result.exit_code == 0, result.output
    assert mock_exec.call_count == 1, "--force must run the workflow despite the held lock"


def test_normal_run_acquires_and_releases_lock(project):
    _, store_dir = project
    with patch("agent_actions.cli.run.RunCommand.execute") as mock_exec:
        result = CliRunner().invoke(run, ["-a", "lock_smoke"])

    assert result.exit_code == 0, result.output
    assert mock_exec.call_count == 1

    # The run released the lock: a fresh non-blocking acquire must succeed.
    lock_path = _lock_path(store_dir, "lock_smoke")
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
