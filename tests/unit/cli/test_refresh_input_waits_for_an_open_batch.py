"""--refresh-input reads the query again, so it waits until no batch is open."""

from pathlib import Path
from types import SimpleNamespace

import click
import pytest

from agent_actions.cli.args import RunCommandArgs
from agent_actions.cli.run import RunCommand


class _State:
    def __init__(self, open_batches: list[str]) -> None:
        self._open = open_batches

    def get_batch_submitted_actions(self, actions: list[str]) -> list[str]:
        return [action for action in actions if action in self._open]


def _workflow(open_batches: list[str]):
    services = SimpleNamespace(core=SimpleNamespace(state_manager=_State(open_batches)))
    return SimpleNamespace(execution_order=["first", "second"], services=services)


def _snapshot(io_dir: Path) -> Path:
    snapshot = io_dir / "_remote_cache" / "database" / "abc" / "data"
    snapshot.mkdir(parents=True)
    return snapshot


def _command() -> RunCommand:
    return RunCommand(
        RunCommandArgs(agent="wf", user_code=None, use_tools=False, refresh_input=True)
    )


def test_an_open_batch_refuses_the_refresh_and_keeps_the_snapshot(tmp_path: Path):
    snapshot = _snapshot(tmp_path)

    with pytest.raises(click.UsageError, match="a batch is still open for second"):
        _command()._refresh_input(_workflow(["second"]), SimpleNamespace(io_dir=tmp_path))

    assert snapshot.exists()


def test_with_no_batch_open_the_snapshot_is_dropped(tmp_path: Path):
    snapshot = _snapshot(tmp_path)

    _command()._refresh_input(_workflow([]), SimpleNamespace(io_dir=tmp_path))

    assert not snapshot.exists()
