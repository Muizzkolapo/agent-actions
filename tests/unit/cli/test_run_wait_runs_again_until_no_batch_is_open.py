"""`agac run --wait` runs the workflow again, as a second `agac run` would, while a batch is open.

Each pass is the pass a second `agac run` makes, so the batch is checked and collected by
the code that does it today. The sleep between passes is handed in, so no test waits.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from agent_actions.cli.args import RunCommandArgs
from agent_actions.cli.exit_codes import EXIT_PAUSED, EXIT_RECORD_FAILURES
from agent_actions.cli.run import RunCommand, run
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
    assert "agac run -a wf" in out


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
