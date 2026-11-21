"""The exit code of `agac run` and `agac retry` is read from the action statuses.

A wrapper told a paused run from a finished one by matching the sentence the command
printed, and both exited 0, as did a run that finished with failed records. The code
comes from the statuses the state manager holds, never from what was printed.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.cli.args import RunCommandArgs
from agent_actions.cli.exit_codes import (
    EXIT_CODES,
    EXIT_FAILED,
    EXIT_PAUSED,
    EXIT_RECORD_FAILURES,
    EXIT_SUCCESS,
    TRACKER_STATUSES,
    RunOutcome,
    classify_outcome,
    run_status,
)
from agent_actions.cli.run import RunCommand
from agent_actions.utils.path_utils import reset_path_manager
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ORDER = ["extract", "classify", "report"]


def _state(tmp_path, *statuses: ActionStatus) -> ActionStateManager:
    state = ActionStateManager(tmp_path / "status.json", ORDER)
    for action, status in zip(ORDER, statuses, strict=True):
        state.update_status(action, status)
    return state


C, P, F, S = (
    ActionStatus.COMPLETED,
    ActionStatus.COMPLETED_WITH_FAILURES,
    ActionStatus.FAILED,
    ActionStatus.SKIPPED,
)

OUTCOMES = [
    ((C, C, C), RunOutcome.SUCCESS, EXIT_SUCCESS),
    ((C, S, C), RunOutcome.SUCCESS, EXIT_SUCCESS),
    ((C, P, C), RunOutcome.RECORD_FAILURES, EXIT_RECORD_FAILURES),
    ((P, S, C), RunOutcome.RECORD_FAILURES, EXIT_RECORD_FAILURES),
    ((C, F, S), RunOutcome.FAILED, EXIT_FAILED),
    ((P, F, S), RunOutcome.FAILED, EXIT_FAILED),
    ((C, ActionStatus.BATCH_SUBMITTED, ActionStatus.PENDING), RunOutcome.PAUSED_FOR_BATCH, 4),
    ((P, ActionStatus.BATCH_SUBMITTED, ActionStatus.PENDING), RunOutcome.PAUSED_FOR_BATCH, 4),
    ((C, ActionStatus.PENDING, ActionStatus.PENDING), RunOutcome.PAUSED, EXIT_PAUSED),
]


@pytest.mark.parametrize(("statuses", "outcome", "code"), OUTCOMES)
def test_each_set_of_action_statuses_has_one_outcome_and_one_exit_code(
    tmp_path, statuses, outcome, code
):
    found = classify_outcome(_state(tmp_path, *statuses), ORDER)

    assert found is outcome
    assert EXIT_CODES[found] == code


def test_run_and_retry_read_the_outcome_through_the_one_classifier():
    from agent_actions.cli import retry, run

    assert retry.classify_outcome is run.classify_outcome is classify_outcome


def test_the_codes_are_the_documented_ones():
    assert (EXIT_SUCCESS, EXIT_FAILED, EXIT_RECORD_FAILURES, EXIT_PAUSED) == (0, 1, 3, 4)


def test_the_run_history_keeps_its_three_statuses():
    assert set(TRACKER_STATUSES.values()) == {"SUCCESS", "PAUSED", "FAILED"}
    assert TRACKER_STATUSES[RunOutcome.RECORD_FAILURES] == "SUCCESS"


@pytest.mark.parametrize(("statuses", "outcome", "code"), OUTCOMES)
def test_the_run_history_status_of_an_outcome_is_the_run_status_of_its_statuses(
    tmp_path, statuses, outcome, code
):
    state = _state(tmp_path, *statuses)

    assert TRACKER_STATUSES[classify_outcome(state, ORDER)] == run_status(state)


class TestRunExitsWithTheCodeOfItsOutcome:
    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        reset_path_manager()
        yield
        reset_path_manager()

    def _run(self, tmp_path, *statuses: ActionStatus) -> int:
        workflow = MagicMock()
        workflow.execution_order = ORDER
        workflow.services.core.state_manager = _state(tmp_path, *statuses)
        tracker = MagicMock()
        tracker.start_workflow_run.return_value = "run-1"
        command = RunCommand(
            RunCommandArgs(agent="wf", user_code=None, use_tools=False, execution_mode="auto")
        )
        with (
            patch("agent_actions.cli.run.ProjectPathsFactory.create_project_paths") as paths,
            patch("agent_actions.cli.run.PromptValidator"),
            patch("agent_actions.cli.run.load_workflow", return_value=workflow),
            patch("agent_actions.cli.run.RunTracker", return_value=tracker),
            patch.object(command, "_run_workflow_execution"),
        ):
            paths.return_value = MagicMock(io_dir=tmp_path)
            try:
                command.execute(project_root=tmp_path)
            except SystemExit as stop:
                return int(stop.code or 0)
        return 0

    def test_a_run_that_finished_with_a_failed_record_exits_3(self, tmp_path, capsys):
        assert self._run(tmp_path, C, P, C) == EXIT_RECORD_FAILURES

        out = capsys.readouterr().out
        assert "failed or exhausted records" in out
        assert "classify" in out

    def test_a_run_paused_for_a_batch_exits_4(self, tmp_path, capsys):
        assert self._run(tmp_path, C, ActionStatus.BATCH_SUBMITTED, ActionStatus.PENDING) == 4

        assert "batch job(s) submitted for: classify" in capsys.readouterr().out

    def test_a_run_that_finished_clean_exits_0(self, tmp_path):
        assert self._run(tmp_path, C, C, C) == EXIT_SUCCESS

    def test_a_run_with_a_failed_action_still_exits_1(self, tmp_path):
        assert self._run(tmp_path, C, F, S) == EXIT_FAILED
