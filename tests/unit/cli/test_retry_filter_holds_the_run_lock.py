"""`agac retry --filter` holds the run lock for all of its work; its dry run takes none."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_actions.cli import retry_filter
from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.retry_filter import RetryFilterCommand
from agent_actions.errors import RunInProgressError
from agent_actions.storage.run_lock import hold_run_lock


def _lock_is_held(io_dir: Path) -> bool:
    try:
        with hold_run_lock(io_dir, "wf"):
            return False
    except RunInProgressError:
        return True


@pytest.mark.parametrize(
    ("dry_run", "held"), [(False, True), (True, False)], ids=["filter", "dry-run"]
)
def test_the_lock_is_held_while_the_filter_works(tmp_path, monkeypatch, dry_run, held):
    io_dir = tmp_path / "agent_io"
    monkeypatch.setattr(
        retry_filter.ProjectPathsFactory,
        "create_project_paths",
        lambda *a, **k: SimpleNamespace(io_dir=io_dir),
    )
    seen: list[bool] = []
    monkeypatch.setattr(
        RetryFilterCommand, "_filter", lambda self, paths, root: seen.append(_lock_is_held(io_dir))
    )
    args = RetryCommandArgs(agent="wf", dry_run=dry_run, filters=[("echo", "r1")], reason="noise")

    RetryFilterCommand(args).execute()

    assert seen == [held]
    assert not _lock_is_held(io_dir)
