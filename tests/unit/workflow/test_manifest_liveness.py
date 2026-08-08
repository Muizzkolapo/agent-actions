"""The manifest records who is running, so readers can tell a live run from a corpse."""

import json
import os
import socket

from agent_actions.workflow.managers.manifest import ManifestManager

EXECUTION_ORDER = ["agent_a", "agent_b"]


def _initialized_manifest(tmp_path):
    manager = ManifestManager(tmp_path)
    manager.initialize_manifest(
        workflow_name="test_workflow",
        execution_order=EXECUTION_ORDER,
        levels=[["agent_a"], ["agent_b"]],
        action_configs={name: {} for name in EXECUTION_ORDER},
    )
    return manager, json.loads((tmp_path / "logs" / ".manifest.json").read_text())


class TestManifestRecordsRunOwner:
    """A status file alone cannot say whether the process that wrote it still exists."""

    def test_records_the_pid_of_the_running_process(self, tmp_path):
        _, written = _initialized_manifest(tmp_path)

        assert written["pid"] == os.getpid()

    def test_records_the_host_so_readers_do_not_trust_a_foreign_pid(self, tmp_path):
        _, written = _initialized_manifest(tmp_path)

        assert written["hostname"] == socket.gethostname()

    def test_owner_is_recorded_before_any_action_starts(self, tmp_path):
        """A run killed during its first action must still be attributable."""
        _, written = _initialized_manifest(tmp_path)

        assert written["status"] == "running"
        assert all(action["status"] == "pending" for action in written["actions"].values())

    def test_owner_survives_marking_the_workflow_finished(self, tmp_path):
        manager, _ = _initialized_manifest(tmp_path)

        manager.mark_workflow_completed()

        written = json.loads((tmp_path / "logs" / ".manifest.json").read_text())
        assert written["pid"] == os.getpid()
        assert written["status"] == "completed"
