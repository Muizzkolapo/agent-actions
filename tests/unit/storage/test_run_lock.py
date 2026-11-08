"""One run per workflow: the run lock is held for the block and refused while held."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_actions.errors import RunInProgressError
from agent_actions.storage.run_lock import hold_run_lock, run_lock_path


def test_the_lock_file_sits_beside_the_workflow_database(tmp_path):
    assert run_lock_path(tmp_path, "wf") == tmp_path / "store" / "wf.db.lock"


def test_a_held_lock_names_its_holder_and_clears_it_when_released(tmp_path):
    with hold_run_lock(tmp_path, "wf"):
        assert run_lock_path(tmp_path, "wf").read_text() == str(os.getpid())

    assert run_lock_path(tmp_path, "wf").read_text() == ""
    with hold_run_lock(tmp_path, "wf"):
        pass


def test_a_second_holder_is_refused_with_the_first_holder_s_pid(tmp_path):
    with hold_run_lock(tmp_path, "wf"):
        with pytest.raises(RunInProgressError) as refused:
            with hold_run_lock(tmp_path, "wf"):
                pytest.fail("the second holder entered the block")

    assert str(refused.value) == (
        f"Another run of workflow 'wf' is in progress (pid {os.getpid()}). "
        "Wait for it to finish or stop it, then run again."
    )


def test_a_refusal_leaves_the_holder_s_pid_in_place(tmp_path):
    with hold_run_lock(tmp_path, "wf"):
        with pytest.raises(RunInProgressError):
            with hold_run_lock(tmp_path, "wf"):
                pass
        assert run_lock_path(tmp_path, "wf").read_text() == str(os.getpid())


def test_two_workflows_do_not_collide(tmp_path):
    with hold_run_lock(tmp_path, "one"), hold_run_lock(tmp_path, "two"):
        assert run_lock_path(tmp_path, "one").exists()
        assert run_lock_path(tmp_path, "two").exists()


def test_the_lock_is_released_when_the_block_raises(tmp_path):
    with pytest.raises(ValueError, match="boom"):
        with hold_run_lock(tmp_path, "wf"):
            raise ValueError("boom")

    with hold_run_lock(tmp_path, "wf"):
        pass


def test_the_store_folder_is_made_when_missing(tmp_path: Path):
    io_dir = tmp_path / "agent_io"

    with hold_run_lock(io_dir, "wf"):
        assert (io_dir / "store").is_dir()
