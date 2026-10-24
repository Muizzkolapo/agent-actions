from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.retry import RetryCommand, _manifest_path, _write_manifest
from agent_actions.workflow.managers.state import REPAIRED_BY, ActionStatus
from tests.unit.cli.conftest import make_mock_backend


def _printed(console: MagicMock) -> str:
    return "\n".join(str(c.args[0]) for c in console.print.call_args_list if c.args)


@pytest.mark.parametrize("dry_run", [True, False])
def test_a_restore_names_each_live_row_it_overwrites(tmp_path: Path, dry_run: bool):
    manifest_file = _manifest_path(tmp_path / "agent_io" / "store" / "test_wf")
    created_at = _write_manifest(
        manifest_file,
        from_action="classify",
        record_ids=["edited", "renamed", "untouched"],
        downstream_actions=["classify"],
        dispositions=[
            {
                "action_name": "classify",
                "record_id": "edited",
                "disposition": "failed",
                "reason": "prompt_too_large",
            },
            {
                "action_name": "classify",
                "record_id": "renamed",
                "disposition": "failed",
                "reason": "timeout",
            },
            {
                "action_name": "classify",
                "record_id": "untouched",
                "disposition": "failed",
                "reason": "timeout",
            },
        ],
    )
    backend = make_mock_backend(
        {
            "classify": [
                {
                    "action_name": "classify",
                    "record_id": "edited",
                    "disposition": "filtered",
                    "reason": "excluded_by_hand",
                },
                {
                    "action_name": "classify",
                    "record_id": "renamed",
                    "disposition": "failed",
                    "reason": "manual_note",
                },
                {
                    "action_name": "classify",
                    "record_id": "untouched",
                    "disposition": "failed",
                    "reason": "timeout",
                },
            ]
        }
    )
    state_mgr = MagicMock()
    state_mgr.get_status_details.return_value = {
        "status": ActionStatus.INTERRUPTED,
        REPAIRED_BY: created_at,
    }
    state_mgr.get_status.return_value = ActionStatus.INTERRUPTED
    state_mgr.get_failed_actions.return_value = []

    with (
        patch("agent_actions.cli.retry.get_storage_backend", return_value=backend),
        patch("agent_actions.cli.retry.ProjectPathsFactory") as paths_factory,
        patch("agent_actions.cli.retry.load_workflow") as load_wf,
    ):
        paths_factory.create_project_paths.return_value.io_dir = tmp_path / "agent_io"
        load_wf.return_value.execution_order = ["classify"]
        load_wf.return_value.services.core.state_manager = state_mgr
        cmd = RetryCommand(RetryCommandArgs(agent="test_wf", dry_run=dry_run))
        cmd.console = MagicMock()
        cmd.execute()

    printed = _printed(cmd.console)
    overwrites = [line.strip() for line in printed.splitlines() if " -> " in line]
    assert overwrites == [
        "classify / edited: filtered (excluded_by_hand) -> failed (prompt_too_large)",
        "classify / renamed: failed (manual_note) -> failed (timeout)",
    ]
    assert str(manifest_file) in printed
