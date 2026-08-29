"""Loading a workflow to read it must not mutate its persisted state.

``AgentWorkflow.__init__`` resets every retryable action to PENDING and wipes
its dispositions before the caller gets the object.  For ``run`` that is the
intent; for ``dispositions``, ``schema`` and ``retry`` it destroys the evidence
those commands exist to show — ``retry`` reads the disposition table *after*
constructing the workflow, so it reports "nothing to retry" about a failure it
has just erased.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.storage.backend import DISPOSITION_FAILED, NODE_LEVEL_RECORD_ID
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ACTION = "collect_questions"
REASON = "Action 'collect_questions': dbt_pages.json: Function 'write_rows' not found"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


@pytest.fixture
def state_manager(tmp_path):
    return ActionStateManager(tmp_path / ".agent_status.json", [ACTION])


def _failed_workflow(tmp_path, backend, state_manager, *, fresh: bool = False) -> AgentWorkflow:
    """A coordinator over a real store holding one genuinely failed action."""
    state_manager.update_status(ACTION, ActionStatus.FAILED, error_message=REASON)
    backend.set_disposition(
        action_name=ACTION,
        record_id=NODE_LEVEL_RECORD_ID,
        disposition=DISPOSITION_FAILED,
        reason=REASON,
    )
    workflow = object.__new__(AgentWorkflow)
    workflow.config = SimpleNamespace(fresh=fresh)
    workflow.storage_backend = backend
    workflow.services = SimpleNamespace(core=SimpleNamespace(state_manager=state_manager))
    return workflow


def _node_rows(backend) -> list[dict]:
    return backend.get_disposition(ACTION, record_id=NODE_LEVEL_RECORD_ID)


class TestAReadOnlyLoadMutatesNothing:
    def test_the_failed_status_survives(self, tmp_path, backend, state_manager):
        workflow = _failed_workflow(tmp_path, backend, state_manager)

        workflow._prepare_state(read_only=True)

        assert state_manager.get_status(ACTION) == ActionStatus.FAILED

    def test_the_disposition_survives(self, tmp_path, backend, state_manager):
        workflow = _failed_workflow(tmp_path, backend, state_manager)

        workflow._prepare_state(read_only=True)

        rows = _node_rows(backend)
        assert len(rows) == 1
        assert rows[0]["reason"] == REASON

    def test_a_fresh_config_is_also_ignored(self, tmp_path, backend, state_manager):
        """read_only outranks --fresh: neither branch may run."""
        workflow = _failed_workflow(tmp_path, backend, state_manager, fresh=True)

        workflow._prepare_state(read_only=True)

        assert state_manager.get_status(ACTION) == ActionStatus.FAILED
        assert len(_node_rows(backend)) == 1


class TestARunLoadStillResets:
    """The run path's reset is intended behaviour and must not regress."""

    def test_the_failed_action_returns_to_pending(self, tmp_path, backend, state_manager):
        workflow = _failed_workflow(tmp_path, backend, state_manager)

        workflow._prepare_state(read_only=False)

        assert state_manager.get_status(ACTION) == ActionStatus.PENDING

    def test_the_disposition_is_cleared(self, tmp_path, backend, state_manager):
        workflow = _failed_workflow(tmp_path, backend, state_manager)

        workflow._prepare_state(read_only=False)

        assert _node_rows(backend) == []


class _StopAtLoad(Exception):
    """Raised in place of load_workflow so execute() stops at the call under test."""


class TestTheReadPathsAskForIt:
    """Each command that only reads state must request a read-only load."""

    @staticmethod
    def _load_kwargs(module: str, command, tmp_path) -> dict:
        with (
            patch(f"agent_actions.cli.{module}.load_workflow", side_effect=_StopAtLoad) as load,
            patch(f"agent_actions.cli.{module}.ProjectPathsFactory") as paths,
            patch(f"agent_actions.cli.{module}.get_storage_backend", create=True),
        ):
            paths.create_project_paths.return_value = MagicMock()
            with pytest.raises(_StopAtLoad):
                command.execute(project_root=tmp_path)
        return load.call_args.kwargs

    def test_dispositions_asks_for_a_read_only_load(self, tmp_path):
        from agent_actions.cli.dispositions import DispositionsCommand

        command = DispositionsCommand(agent="wf", action=None, quarantined=False)
        assert self._load_kwargs("dispositions", command, tmp_path).get("read_only") is True

    def test_schema_asks_for_a_read_only_load(self, tmp_path):
        from agent_actions.cli.schema import SchemaCommand

        command = SchemaCommand(agent="wf", user_code=None, json_output=False, verbose=False)
        assert self._load_kwargs("schema", command, tmp_path).get("read_only") is True

    def test_retry_asks_for_a_read_only_load_in_both_modes(self, tmp_path):
        """retry owns its own state transitions and reads dispositions after loading."""
        from agent_actions.cli.args import RetryCommandArgs
        from agent_actions.cli.retry import RetryCommand

        for dry_run in (True, False):
            command = RetryCommand(RetryCommandArgs(agent="wf", dry_run=dry_run))
            with patch("agent_actions.cli.retry._read_manifest", return_value=None):
                kwargs = self._load_kwargs("retry", command, tmp_path)
            assert kwargs.get("read_only") is True, f"dry_run={dry_run}"

    def test_run_does_not_ask_for_one(self, tmp_path):
        """run's reset-before-execute is the intended behaviour and must survive."""
        from agent_actions.cli.args import RunCommandArgs
        from agent_actions.cli.run import RunCommand

        with (
            patch("agent_actions.cli.run.load_workflow", side_effect=_StopAtLoad) as load,
            patch("agent_actions.cli.run.ProjectPathsFactory") as paths,
            patch("agent_actions.cli.run.PromptValidator"),
        ):
            paths.create_project_paths.return_value = MagicMock()
            with pytest.raises(_StopAtLoad):
                RunCommand(RunCommandArgs(agent="wf")).execute(project_root=tmp_path)

        assert load.call_args.kwargs.get("read_only") is not True
