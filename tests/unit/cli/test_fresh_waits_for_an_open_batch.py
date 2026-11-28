"""--fresh drops a batch not yet collected only with --abandon-in-flight (#1921)."""

import json
from pathlib import Path
from types import SimpleNamespace

import click
import pytest

from agent_actions.cli.args import RunCommandArgs
from agent_actions.cli.run import RunCommand


def _io(tmp_path: Path, statuses: dict[str, str]) -> SimpleNamespace:
    io_dir = tmp_path / "agent_io"
    io_dir.mkdir()
    (io_dir / ".agent_status.json").write_text(
        json.dumps({action: {"status": status} for action, status in statuses.items()})
    )
    return SimpleNamespace(io_dir=io_dir)


def _command(abandon_in_flight: bool = False) -> RunCommand:
    return RunCommand(
        RunCommandArgs(
            agent="wf",
            user_code=None,
            use_tools=False,
            fresh=True,
            abandon_in_flight=abandon_in_flight,
        )
    )


@pytest.mark.parametrize("status", ["batch_submitted", "checking_batch"])
def test_an_action_waiting_on_a_batch_refuses_fresh(tmp_path, status):
    paths = _io(tmp_path, {"first": "completed", "second": status})

    with pytest.raises(
        click.UsageError, match="--fresh would drop the batch still open for second"
    ):
        _command()._refuse_fresh_over_an_open_batch(paths)


def test_abandon_in_flight_lets_fresh_drop_it(tmp_path):
    paths = _io(tmp_path, {"first": "batch_submitted"})

    _command(abandon_in_flight=True)._refuse_fresh_over_an_open_batch(paths)


def test_with_no_batch_open_fresh_goes_on(tmp_path):
    _command()._refuse_fresh_over_an_open_batch(_io(tmp_path, {"first": "completed"}))


def test_batch_state_that_cannot_be_read_does_not_stop_fresh(tmp_path, monkeypatch, caplog):
    """--fresh is how such a store is started over: the error that names it says so."""

    def unreadable(*args):
        raise ValueError("unknown recovery_type 'bogus'")

    monkeypatch.setattr("agent_actions.cli.run.batches_still_open", unreadable)

    _command()._refuse_fresh_over_an_open_batch(_io(tmp_path, {"first": "batch_submitted"}))

    assert "Could not tell whether a batch is still open" in caplog.text
