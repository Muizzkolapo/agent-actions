"""`agac run --wait` runs the workflow again, as a second `agac run` would, while a batch is open.

Each pass is the pass a second `agac run` makes, so the batch is checked and collected by
the code that does it today. The sleep between passes is handed in, so no test waits.

Without `--poll` a real run waits the default between two passes. A sandbox run does not
wait, since the mock answers at once; while its scenario holds each batch for a time, it
waits that time, at most one second. A `--poll` given is used as given in both.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from agent_actions.cli.args import DEFAULT_POLL_SECONDS, RunCommandArgs
from agent_actions.cli.exit_codes import EXIT_PAUSED, EXIT_RECORD_FAILURES
from agent_actions.cli.run import RunCommand, run
from agent_actions.config import sandbox
from agent_actions.utils.path_utils import reset_path_manager
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ORDER = ["extract", "classify"]
OPEN = (ActionStatus.COMPLETED, ActionStatus.BATCH_SUBMITTED)
DONE = (ActionStatus.COMPLETED, ActionStatus.COMPLETED)
PARTIAL = (ActionStatus.COMPLETED, ActionStatus.COMPLETED_WITH_FAILURES)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_path_manager()
    yield
    reset_path_manager()


class Passes:
    """A workflow whose statuses after each pass are given; records how it was loaded."""

    def __init__(self, tmp_path, *after_each_pass):
        self.tmp_path = tmp_path
        self.after_each_pass = list(after_each_pass)
        self.loads: list[dict] = []
        self.slept: list[float] = []

    def _load(self, *_args, **kwargs):
        self.loads.append(kwargs)
        state = ActionStateManager(self.tmp_path / f"status{len(self.loads)}.json", ORDER)
        for action, status in zip(ORDER, self.after_each_pass.pop(0), strict=True):
            state.update_status(action, status)
        workflow = MagicMock()
        workflow.execution_order = ORDER
        workflow.services.core.state_manager = state
        return workflow

    def run(self, sleep=None, **args) -> int:
        tracker = MagicMock()
        tracker.start_workflow_run.return_value = "run-1"
        command = RunCommand(
            RunCommandArgs(
                agent="wf", user_code=None, use_tools=False, execution_mode="auto", **args
            ),
            sleep=sleep or self.slept.append,
        )
        with (
            patch("agent_actions.cli.run.ProjectPathsFactory.create_project_paths") as paths,
            patch("agent_actions.cli.run.PromptValidator"),
            patch("agent_actions.cli.run.load_workflow", side_effect=self._load),
            patch("agent_actions.cli.run.RunTracker", return_value=tracker),
            patch.object(command, "_run_workflow_execution"),
        ):
            paths.return_value = MagicMock(io_dir=self.tmp_path)
            try:
                command.execute(project_root=self.tmp_path)
            except SystemExit as stop:
                return int(stop.code or 0)
        return 0


def test_it_runs_again_until_no_batch_is_open_and_exits_0(tmp_path):
    passes = Passes(tmp_path, OPEN, OPEN, DONE)

    code = passes.run(wait=True, poll=7)

    assert code == 0
    assert len(passes.loads) == 3
    assert passes.slept == [7, 7]


def test_without_wait_a_paused_run_stops_after_one_pass(tmp_path):
    passes = Passes(tmp_path, OPEN, DONE)

    code = passes.run()

    assert code == EXIT_PAUSED
    assert len(passes.loads) == 1
    assert passes.slept == []


def test_it_exits_with_the_code_of_the_status_the_last_pass_ended_with(tmp_path):
    passes = Passes(tmp_path, OPEN, PARTIAL)

    assert passes.run(wait=True, poll=1) == EXIT_RECORD_FAILURES


def test_only_the_first_pass_clears_or_reruns_anything(tmp_path):
    passes = Passes(tmp_path, OPEN, DONE)

    passes.run(wait=True, poll=1, fresh=True, rerun=("extract",))

    assert (passes.loads[0]["fresh"], tuple(passes.loads[0]["rerun"])) == (True, ("extract",))
    assert (passes.loads[1]["fresh"], tuple(passes.loads[1]["rerun"])) == (False, ())


def test_at_the_timeout_it_exits_4_and_says_how_to_resume(tmp_path, capsys):
    passes = Passes(tmp_path, OPEN, OPEN, OPEN)

    code = passes.run(wait=True, poll=5, wait_timeout=0)

    assert code == EXIT_PAUSED
    assert len(passes.loads) == 1
    assert passes.slept == []
    out = capsys.readouterr().out
    assert "still open" in out
    assert "classify" in out
    assert "agac run -w wf --wait" in out


def test_it_never_sleeps_past_the_timeout(tmp_path, capsys):
    passes = Passes(tmp_path, OPEN, OPEN, OPEN, OPEN)
    now = [1000.0]

    def sleep(seconds: float) -> None:
        passes.slept.append(seconds)
        now[0] += seconds

    with patch("agent_actions.cli.run.time.monotonic", side_effect=lambda: now[0]):
        code = passes.run(sleep=sleep, wait=True, poll=40, wait_timeout=100)

    assert code == EXIT_PAUSED
    assert passes.slept == [40, 40, 20]
    assert "still open" in capsys.readouterr().out


def test_it_holds_the_run_lock_from_the_first_pass_to_the_last(tmp_path):
    passes = Passes(tmp_path, OPEN, DONE)
    held: list[str] = []

    class Lock:
        def __enter__(self):
            held.append("taken")

        def __exit__(self, *exc):
            held.append(f"released after {len(passes.loads)} pass(es)")

    with patch("agent_actions.cli.run.hold_run_lock", return_value=Lock()):
        passes.run(wait=True, poll=1)

    assert held == ["taken", "released after 2 pass(es)"]


@pytest.mark.parametrize("flag", [["--poll", "5"], ["--wait-timeout", "60"]])
def test_poll_and_wait_timeout_are_refused_without_wait(tmp_path, monkeypatch, flag):
    (tmp_path / "agent_actions.yml").write_text("project_name: p\n")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(run, ["-a", "wf", *flag])

    assert result.exit_code == 2
    assert "--wait" in result.output


class _Clock:
    """A monotonic clock that a pass and a sleep move forward."""

    def __init__(self, passes: Passes, each_pass: float):
        self.now = 1000.0
        load = passes._load

        def timed_load(*args, **kwargs):
            self.now += each_pass
            return load(*args, **kwargs)

        passes._load = timed_load

    def sleep(self, passes: Passes):
        def sleep(seconds: float) -> None:
            passes.slept.append(seconds)
            self.now += seconds

        return sleep


def test_the_wait_timeout_counts_from_before_the_first_pass(tmp_path, capsys):
    passes = Passes(tmp_path, OPEN, OPEN, OPEN, OPEN)
    clock = _Clock(passes, each_pass=30)

    with patch("agent_actions.cli.run.time.monotonic", side_effect=lambda: clock.now):
        code = passes.run(sleep=clock.sleep(passes), wait=True, poll=10, wait_timeout=50)

    assert code == EXIT_PAUSED
    assert len(passes.loads) == 2
    assert passes.slept == [10]
    assert "Stopped waiting after 70s:" in capsys.readouterr().out


def test_the_printed_wait_is_the_time_slept_and_no_pass_runs_after_the_timeout(tmp_path, capsys):
    passes = Passes(tmp_path, OPEN, OPEN, OPEN)
    clock = _Clock(passes, each_pass=0.4)

    with patch("agent_actions.cli.run.time.monotonic", side_effect=lambda: clock.now):
        code = passes.run(sleep=clock.sleep(passes), wait=True, poll=5, wait_timeout=7)

    out = capsys.readouterr().out
    assert code == EXIT_PAUSED
    assert passes.slept == [5, pytest.approx(1.2)]
    assert clock.now == pytest.approx(1007)
    assert len(passes.loads) == 2
    assert "Waiting 5s before" in out and "Waiting 1.2s before" in out
    assert "Stopped waiting after 7s:" in out


@pytest.mark.parametrize("poll", ["0", "0.5", "1.5"])
def test_a_poll_that_is_not_a_whole_number_of_seconds_from_one_up_is_refused(
    tmp_path, monkeypatch, poll
):
    (tmp_path / "agent_actions.yml").write_text("project_name: p\n")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(run, ["-w", "wf", "--wait", "--poll", poll])

    assert result.exit_code == 2
    assert "--poll" in result.output


def test_a_pause_with_no_open_batch_exits_4_and_says_wait_has_nothing_to_wait_for(
    tmp_path, capsys
):
    passes = Passes(tmp_path, (ActionStatus.COMPLETED, ActionStatus.PENDING))

    code = passes.run(wait=True, poll=5)

    assert code == EXIT_PAUSED
    assert passes.slept == []
    assert (
        "--wait has no batch to wait for: the run stopped before every action ended."
        in capsys.readouterr().out
    )


def test_without_a_poll_a_real_run_waits_the_default_between_passes(tmp_path, capsys):
    passes = Passes(tmp_path, OPEN, OPEN, DONE)

    code = passes.run(wait=True)

    assert code == 0
    assert passes.slept == [DEFAULT_POLL_SECONDS, DEFAULT_POLL_SECONDS]
    assert f"Waiting {DEFAULT_POLL_SECONDS}s before" in capsys.readouterr().out


@pytest.fixture
def in_a_sandbox(tmp_path):
    """A sandbox run that follows the scenario written to *tmp_path*, the happy preset if none."""

    def follow(scenario: str | None = None):
        if scenario is not None:
            (tmp_path / "sandbox.yml").write_text(scenario)
        sandbox.load_scenario(tmp_path, {"classify": None})

    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        yield follow


def test_without_a_poll_a_sandbox_run_checks_again_with_no_wait(tmp_path, capsys, in_a_sandbox):
    in_a_sandbox()
    passes = Passes(tmp_path, OPEN, OPEN, DONE)

    code = passes.run(wait=True)

    assert code == 0
    assert len(passes.loads) == 3
    assert passes.slept == []
    out = capsys.readouterr().out
    assert out.count("Checking the batch job(s) again...") == 2
    assert "Waiting" not in out


def test_a_poll_given_to_a_sandbox_run_is_used_as_given(tmp_path, capsys, in_a_sandbox):
    in_a_sandbox()
    passes = Passes(tmp_path, OPEN, OPEN, DONE)

    passes.run(wait=True, poll=7)

    assert passes.slept == [7, 7]
    assert "Waiting 7s before" in capsys.readouterr().out


@pytest.mark.parametrize(("held", "waited"), [(5, 1), (1, 1), (0.25, 0.25)])
def test_while_the_scenario_holds_a_batch_by_time_a_sandbox_run_waits_at_most_a_second(
    tmp_path, capsys, in_a_sandbox, held, waited
):
    in_a_sandbox(f"batch: {{complete_after_seconds: {held}}}\n")
    passes = Passes(tmp_path, OPEN, OPEN, OPEN, DONE)

    code = passes.run(wait=True)

    assert code == 0
    assert passes.slept == [waited] * 3
    assert capsys.readouterr().out.count(f"Waiting {waited:g}s before checking") == 3


def test_a_scenario_that_holds_a_batch_by_status_checks_alone_adds_no_wait(tmp_path, in_a_sandbox):
    in_a_sandbox("batch: {polls_until_complete: 3}\n")
    passes = Passes(tmp_path, OPEN, OPEN, OPEN, DONE)

    passes.run(wait=True)

    assert passes.slept == []
    assert len(passes.loads) == 4


def test_a_sandbox_wait_with_no_pause_still_stops_at_the_timeout(tmp_path, capsys, in_a_sandbox):
    in_a_sandbox()
    passes = Passes(tmp_path, OPEN, OPEN, OPEN, OPEN)
    clock = _Clock(passes, each_pass=30)

    with patch("agent_actions.cli.run.time.monotonic", side_effect=lambda: clock.now):
        code = passes.run(sleep=clock.sleep(passes), wait=True, wait_timeout=50)

    assert code == EXIT_PAUSED
    assert len(passes.loads) == 2
    assert passes.slept == []
    assert "Stopped waiting after 60s:" in capsys.readouterr().out


@pytest.mark.parametrize(("flags", "poll"), [([], None), (["--poll", "3"], 3)])
def test_the_command_keeps_whether_a_poll_was_given(tmp_path, monkeypatch, flags, poll):
    (tmp_path / "agent_actions.yml").write_text("project_name: p\n")
    monkeypatch.chdir(tmp_path)

    with patch("agent_actions.cli.run.RunCommand") as command:
        result = CliRunner().invoke(run, ["-w", "wf", "--sandbox", "--wait", *flags])

    assert result.exit_code == 0, result.output
    assert command.call_args[0][0].poll == poll
