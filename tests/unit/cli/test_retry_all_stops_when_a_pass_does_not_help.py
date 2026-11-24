"""The stop rules of `agac retry --all`, with each pass stood in for.

A pass is one retry from the earliest failure. `--all` repeats it while a pass closes
an open failure, an (action, record) pair: it stops when none is left, when a pass closed
none, when a pass left the failures an earlier pass left, at `--max-passes`, and when a
pass paused for a batch. The exit code is the code of the
last pass's outcome, and 3 whenever a failure is still open.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.exit_codes import (
    EXIT_FAILED,
    EXIT_PAUSED,
    EXIT_QUOTA_STOP,
    EXIT_RECORD_FAILURES,
    EXIT_SUCCESS,
    RunOutcome,
)
from agent_actions.cli.retry import RetryCommand
from agent_actions.errors import ProviderQuotaStop

pytestmark = pytest.mark.usefixtures("a_store_exists")

CLEAN, PARTIAL = RunOutcome.SUCCESS, RunOutcome.RECORD_FAILURES


def _open(failures) -> frozenset[tuple[str, str]]:
    """A count stands for that many failures at action `a`; a string names `action:record`."""
    if isinstance(failures, int):
        return frozenset(("a", str(n)) for n in range(failures))
    return frozenset(tuple(name.split(":")) for name in failures)


class Passes:
    """Each pass is (open failures before it, its outcome, open failures after it)."""

    def __init__(self, tmp_path, *passes, **args):
        self.passes = list(passes)
        self.ran = 0
        self.locks: list[str] = []
        self.command = RetryCommand(RetryCommandArgs(agent="wf", all=True, **args))
        self.command.console = MagicMock()
        self.tmp_path = tmp_path

    def _retry(self, _paths, _project_root):
        before, outcome, _after = self.passes[self.ran]
        self.ran += 1
        self.command._open_before = _open(before)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def _open_failures(self, _paths) -> frozenset[tuple[str, str]]:
        return _open(self.passes[self.ran - 1][2])

    def run(self) -> int:
        lock = MagicMock()
        lock.__enter__.side_effect = lambda: self.locks.append("taken")
        lock.__exit__.side_effect = lambda *exc: self.locks.append(f"released after {self.ran}")
        with (
            patch("agent_actions.cli.retry.ProjectPathsFactory.create_project_paths") as paths,
            patch("agent_actions.cli.retry.hold_run_lock", return_value=lock),
            patch.object(self.command, "_retry", self._retry),
            patch.object(self.command, "_open_failures", self._open_failures),
        ):
            paths.return_value = MagicMock(io_dir=self.tmp_path)
            try:
                self.command.execute(project_root=self.tmp_path)
            except SystemExit as stop:
                return int(stop.code or 0)
        return EXIT_SUCCESS

    @property
    def printed(self) -> str:
        return "\n".join(str(call.args[0]) for call in self.command.console.print.call_args_list)


def test_it_repeats_while_the_count_goes_down_and_exits_0_when_none_is_left(tmp_path):
    passes = Passes(tmp_path, (4, PARTIAL, 2), (2, CLEAN, 0))

    assert passes.run() == EXIT_SUCCESS
    assert passes.ran == 2
    assert "Pass 1: 2 open failure(s) left" in passes.printed
    assert "Pass 2: 0 open failure(s) left" in passes.printed


def test_it_stops_after_a_pass_that_closed_none_of_the_open_failures(tmp_path):
    passes = Passes(tmp_path, (2, PARTIAL, 2), (2, CLEAN, 0))

    assert passes.run() == EXIT_RECORD_FAILURES
    assert passes.ran == 1
    assert "closed none of the open failures (2 before it, 2 after)" in passes.printed


def test_it_goes_on_when_a_pass_closes_failures_and_as_many_open_at_a_later_action(tmp_path):
    passes = Passes(
        tmp_path,
        (["a:t1", "a:t2"], PARTIAL, ["b:t1", "b:t2"]),
        (["b:t1", "b:t2"], CLEAN, []),
    )

    assert passes.run() == EXIT_SUCCESS
    assert passes.ran == 2
    assert "Pass 1: 2 open failure(s) left" in passes.printed


def test_it_goes_on_when_a_pass_closes_one_failure_and_more_open(tmp_path):
    passes = Passes(
        tmp_path, (["a:t1", "a:t2"], PARTIAL, ["a:t2", "b:t1", "b:t3"]), (["a:t2"], CLEAN, [])
    )

    assert passes.run() == EXIT_SUCCESS
    assert passes.ran == 2


def test_it_stops_when_a_pass_leaves_the_failures_an_earlier_pass_left(tmp_path):
    passes = Passes(
        tmp_path,
        (["a:t1"], PARTIAL, ["b:t1"]),
        (["b:t1"], PARTIAL, ["a:t1"]),
        (["a:t1"], CLEAN, []),
    )

    assert passes.run() == EXIT_RECORD_FAILURES
    assert passes.ran == 2
    assert "left the same open failures as an earlier pass" in passes.printed


def test_it_stops_after_a_pass_that_left_more_failures_than_it_found(tmp_path):
    passes = Passes(tmp_path, (2, PARTIAL, 3), (3, CLEAN, 0))

    assert passes.run() == EXIT_RECORD_FAILURES
    assert passes.ran == 1


def test_it_stops_at_max_passes_while_the_count_still_goes_down(tmp_path):
    passes = Passes(tmp_path, (6, PARTIAL, 4), (4, PARTIAL, 2), (2, CLEAN, 0), max_passes=2)

    assert passes.run() == EXIT_RECORD_FAILURES
    assert passes.ran == 2
    assert "--max-passes 2 with 2 open failure(s) left" in passes.printed


def test_max_passes_is_not_named_when_the_last_allowed_pass_left_nothing(tmp_path):
    passes = Passes(tmp_path, (2, CLEAN, 0), max_passes=1)

    assert passes.run() == EXIT_SUCCESS
    assert "--max-passes" not in passes.printed


def test_a_failed_action_after_the_last_pass_exits_1(tmp_path):
    passes = Passes(tmp_path, (3, RunOutcome.FAILED, 3))

    assert passes.run() == EXIT_FAILED


def test_a_pass_that_paused_for_a_batch_ends_it_with_exit_4(tmp_path):
    """Its records wait on the batch, so the count went down and nothing is repaired yet."""
    passes = Passes(tmp_path, (4, RunOutcome.PAUSED_FOR_BATCH, 2), (2, CLEAN, 0))

    assert passes.run() == EXIT_PAUSED
    assert passes.ran == 1


def test_a_failure_still_open_is_exit_3_whatever_the_statuses_say(tmp_path):
    passes = Passes(tmp_path, (2, CLEAN, 2))

    assert passes.run() == EXIT_RECORD_FAILURES


def test_with_nothing_to_retry_it_exits_0_and_counts_no_pass(tmp_path):
    passes = Passes(tmp_path, (0, None, 0))

    assert passes.run() == EXIT_SUCCESS
    assert "Pass 1" not in passes.printed


def test_a_quota_stop_in_a_later_pass_ends_it_with_exit_5(tmp_path, capsys):
    stop = ProviderQuotaStop("lab", "no credit left")
    passes = Passes(tmp_path, (4, PARTIAL, 2), (2, stop, 2))

    assert passes.run() == EXIT_QUOTA_STOP
    assert passes.ran == 2
    assert "Provider quota or billing stop (lab)" in capsys.readouterr().err


def test_it_holds_the_run_lock_from_the_first_pass_to_the_last(tmp_path):
    passes = Passes(tmp_path, (4, PARTIAL, 2), (2, CLEAN, 0))

    passes.run()

    assert passes.locks == ["taken", "released after 2"]


def test_a_dry_run_makes_one_pass_takes_no_lock_and_says_how_many_are_open(tmp_path):
    passes = Passes(tmp_path, (5, None, 5), dry_run=True)

    assert passes.run() == EXIT_SUCCESS
    assert passes.ran == 1
    assert passes.locks == []
    assert "--all: 5 open failure(s)" in passes.printed


@pytest.mark.parametrize("max_passes", [0, -1])
def test_max_passes_is_at_least_one(max_passes):
    with pytest.raises(ValueError, match="max_passes"):
        RetryCommandArgs(agent="wf", all=True, max_passes=max_passes)
