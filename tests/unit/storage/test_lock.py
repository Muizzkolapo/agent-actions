"""Unit tests for the VIOL-0045 advisory workflow lock helper."""

from __future__ import annotations

import os

import pytest

from agent_actions.storage.lock import WorkflowLockHeld, workflow_lock


def test_acquires_creates_file_and_stamps_pid(tmp_path):
    with workflow_lock(tmp_path, "wf") as lock_path:
        assert lock_path == tmp_path / "wf.db.lock"
        assert lock_path.exists()
        assert lock_path.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_second_acquire_while_held_raises_with_pid(tmp_path):
    with workflow_lock(tmp_path, "wf"):
        with pytest.raises(WorkflowLockHeld) as ei:
            with workflow_lock(tmp_path, "wf"):
                pass
    assert ei.value.pid == os.getpid()
    assert ei.value.lock_path == tmp_path / "wf.db.lock"
    message = str(ei.value).lower()
    assert "another" in message
    assert "pid" in message
    assert "--force" in message


def test_lock_is_reacquirable_after_release(tmp_path):
    with workflow_lock(tmp_path, "wf"):
        pass
    # Released — a fresh acquire must succeed rather than raise.
    with workflow_lock(tmp_path, "wf") as lock_path:
        assert lock_path.exists()


def test_different_workflows_do_not_collide(tmp_path):
    with workflow_lock(tmp_path, "a"):
        with workflow_lock(tmp_path, "b") as b_path:
            assert b_path == tmp_path / "b.db.lock"


def test_store_dir_created_on_demand(tmp_path):
    store_dir = tmp_path / "agent_io" / "store"
    assert not store_dir.exists()
    with workflow_lock(store_dir, "wf") as lock_path:
        assert store_dir.is_dir()
        assert lock_path.parent == store_dir


def test_stale_pid_body_does_not_block_reacquire(tmp_path):
    """A leftover lock file body (e.g. from a SIGKILLed run) must not itself
    block a new acquire — the OS lock, not the pid text, is the mutex."""
    lock_path = tmp_path / "wf.db.lock"
    lock_path.write_text("999999", encoding="utf-8")
    with workflow_lock(tmp_path, "wf") as held:
        assert held == lock_path
        assert held.read_text(encoding="utf-8").strip() == str(os.getpid())
