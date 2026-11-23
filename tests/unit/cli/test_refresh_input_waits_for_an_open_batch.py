"""--refresh-input reads the query again, so it waits until no batch is open.

The check reads what is stored, before the workflow loads: loading with --rerun
clears state, and the refusal must come before anything is cleared.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import click
import pytest

from agent_actions.cli.args import RunCommandArgs
from agent_actions.cli.run import RunCommand, batches_still_open
from agent_actions.input.loaders import database_source


def _io(tmp_path: Path, statuses: dict[str, str]) -> Path:
    io_dir = tmp_path / "agent_io"
    io_dir.mkdir()
    (io_dir / ".agent_status.json").write_text(
        json.dumps({action: {"status": status} for action, status in statuses.items()})
    )
    return io_dir


def _command(fresh: bool = False) -> RunCommand:
    return RunCommand(
        RunCommandArgs(agent="wf", user_code=None, use_tools=False, refresh_input=True, fresh=fresh)
    )


@pytest.mark.parametrize("status", ["batch_submitted", "checking_batch"])
def test_an_action_waiting_on_a_batch_refuses_the_refresh(tmp_path, status):
    io_dir = _io(tmp_path, {"first": "completed", "second": status})

    with pytest.raises(click.UsageError, match="a batch is still open for second"):
        _command()._refresh_input(SimpleNamespace(io_dir=io_dir))

    assert not database_source._refresh_requested


def test_with_no_batch_open_the_refresh_is_requested(tmp_path):
    io_dir = _io(tmp_path, {"first": "completed"})

    _command()._refresh_input(SimpleNamespace(io_dir=io_dir))

    assert database_source._refresh_requested


def test_a_fresh_run_discards_the_batches_so_it_may_refresh(tmp_path):
    io_dir = _io(tmp_path, {"first": "batch_submitted"})

    _command(fresh=True)._refresh_input(SimpleNamespace(io_dir=io_dir))

    assert database_source._refresh_requested


def test_a_project_never_run_has_no_open_batch(tmp_path):
    assert batches_still_open(tmp_path / "agent_io", "wf") == []
