"""`RunCommand.execute` calls *holding_the_lock* before it releases the run lock.

`agac sandbox check` reads what its run wrote there, so no other run of the workflow can
write between the end of the run and the read. It is called however the run ends.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.cli.args import RunCommandArgs
from agent_actions.cli.exit_codes import RunOutcome
from agent_actions.cli.run import RunCommand
from agent_actions.errors import RunInProgressError
from agent_actions.storage.run_lock import hold_run_lock
from agent_actions.utils.path_utils import reset_path_manager


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_path_manager()
    yield
    reset_path_manager()


def _execute(tmp_path, run_pass, holding_the_lock) -> None:
    command = RunCommand(
        RunCommandArgs(agent="wf", user_code=None, use_tools=False, execution_mode="auto")
    )
    with (
        patch("agent_actions.cli.run.ProjectPathsFactory.create_project_paths") as paths,
        patch.object(command, "_run_holding_the_lock", side_effect=run_pass),
    ):
        paths.return_value = MagicMock(io_dir=tmp_path)
        command.execute(project_root=tmp_path, holding_the_lock=holding_the_lock)


def _lock_is_held(tmp_path) -> bool:
    try:
        with hold_run_lock(tmp_path, "wf"):
            return False
    except RunInProgressError:
        return True


def test_it_is_called_while_the_run_lock_is_held(tmp_path):
    seen: list[bool] = []

    _execute(
        tmp_path,
        lambda *_a, **_k: RunOutcome.SUCCESS,
        lambda: seen.append(_lock_is_held(tmp_path)),
    )

    assert seen == [True]
    assert not _lock_is_held(tmp_path)


def test_it_is_called_when_the_run_raises(tmp_path):
    seen: list[bool] = []

    def fails(*_args, **_kwargs):
        raise RuntimeError("the run broke")

    with pytest.raises(RuntimeError, match="the run broke"):
        _execute(tmp_path, fails, lambda: seen.append(_lock_is_held(tmp_path)))

    assert seen == [True]


def test_it_is_not_called_when_another_run_holds_the_lock(tmp_path):
    called: list[bool] = []

    with hold_run_lock(tmp_path, "wf"), pytest.raises(RunInProgressError):
        _execute(tmp_path, lambda *_a, **_k: RunOutcome.SUCCESS, lambda: called.append(True))

    assert called == []
