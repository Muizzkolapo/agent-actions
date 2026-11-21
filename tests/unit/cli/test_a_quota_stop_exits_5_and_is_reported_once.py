"""`agac run` ends a provider quota stop with exit 5, reported once.

The workflow reports the stop where it marks its actions interrupted, and tags it as
shown; the command prints it only when nothing has, and never a second time.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.cli.args import RunCommandArgs
from agent_actions.cli.exit_codes import (
    EXIT_CODES,
    EXIT_QUOTA_STOP,
    TRACKER_STATUSES,
    RunOutcome,
)
from agent_actions.cli.run import RunCommand
from agent_actions.errors import ProviderQuotaStop
from agent_actions.utils.path_utils import reset_path_manager

MESSAGE = (
    "Provider quota or billing stop (ollama_cloud): monthly usage limit reached. "
    "Add credits, then run again to resume."
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_path_manager()
    yield
    reset_path_manager()


def _run(tmp_path, stop: ProviderQuotaStop, **args) -> tuple[int, MagicMock]:
    workflow = MagicMock()
    workflow.execution_order = ["classify"]
    tracker = MagicMock()
    tracker.start_workflow_run.return_value = "run-1"
    command = RunCommand(
        RunCommandArgs(agent="wf", user_code=None, use_tools=False, execution_mode="auto", **args),
        sleep=lambda _seconds: pytest.fail("a stopped run does not wait"),
    )
    with (
        patch("agent_actions.cli.run.ProjectPathsFactory.create_project_paths") as paths,
        patch("agent_actions.cli.run.PromptValidator"),
        patch("agent_actions.cli.run.load_workflow", return_value=workflow),
        patch("agent_actions.cli.run.RunTracker", return_value=tracker),
        patch.object(command, "_run_workflow_execution", side_effect=stop),
    ):
        paths.return_value = MagicMock(io_dir=tmp_path)
        with pytest.raises(SystemExit) as stopped:
            command.execute(project_root=tmp_path)
    return int(stopped.value.code), tracker


def test_the_code_is_5():
    assert EXIT_QUOTA_STOP == EXIT_CODES[RunOutcome.QUOTA_STOP] == 5


def test_a_quota_stop_exits_5(tmp_path):
    code, _ = _run(tmp_path, ProviderQuotaStop("ollama_cloud", "monthly usage limit reached"))

    assert code == EXIT_QUOTA_STOP


def test_the_message_names_the_provider_its_text_and_the_remedy(tmp_path, capsys):
    _run(tmp_path, ProviderQuotaStop("ollama_cloud", "monthly usage limit reached."))

    assert capsys.readouterr().err.strip() == MESSAGE


def test_a_stop_the_workflow_has_shown_is_not_printed_again(tmp_path, capsys):
    stop = ProviderQuotaStop("ollama_cloud", "monthly usage limit reached")
    stop._already_displayed = True

    code, _ = _run(tmp_path, stop)

    assert code == EXIT_QUOTA_STOP
    captured = capsys.readouterr()
    assert "quota" not in captured.out + captured.err


def test_the_run_history_records_it_as_paused_with_the_message(tmp_path):
    _, tracker = _run(tmp_path, ProviderQuotaStop("ollama_cloud", "monthly usage limit reached"))

    recorded = tracker.finalize_workflow_run.call_args.kwargs
    assert recorded["status"] == TRACKER_STATUSES[RunOutcome.QUOTA_STOP] == "PAUSED"
    assert recorded["error_message"] == MESSAGE


def test_wait_does_not_run_again_after_a_stop(tmp_path):
    code, _ = _run(tmp_path, ProviderQuotaStop("lab", "no credit"), wait=True, poll=1)

    assert code == EXIT_QUOTA_STOP
