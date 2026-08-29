"""An ``on_exhausted: raise`` halt must survive the next ``agac run``.

``raise`` means "stop, a human needs to look at this".  The failure is
deterministic — same input, same config, same outcome — so re-running it costs
real model calls and ends in the identical halt, forever.  Two things let that
happen: the startup reset returns the action to PENDING and wipes the evidence,
and the executor has no branch for FAILED, so it re-runs the action regardless
of what the status says.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import AgentActionsError, DependencyError
from agent_actions.storage.backend import DISPOSITION_FAILED, NODE_LEVEL_RECORD_ID
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.executor import (
    ActionExecutor,
    ActionRunParams,
    ExecutorDependencies,
)
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

HALTED = "summarize_page_content"
ORDINARY = "author_stem"
HALT_MESSAGE = "Retry exhausted for record 34d2c361 after 2 attempts (on_exhausted=raise)"
# Persisted in the store and read back on the next run, so the literal is
# pinned here rather than imported — changing it strands existing halts.
HALT_MARKER = "halted_on_exhausted"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


@pytest.fixture
def state_manager(tmp_path):
    return ActionStateManager(tmp_path / ".agent_status.json", [HALTED, ORDINARY])


def _halt_error() -> AgentActionsError:
    """The exception result_collector raises when on_exhausted=raise fires."""
    return AgentActionsError(
        HALT_MESSAGE,
        context={"agent_name": HALTED, "exhausted_records": 1, "on_exhausted": "raise"},
    )


def _executor(backend, state_manager) -> ActionExecutor:
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = state_manager
    deps.action_runner = MagicMock()
    deps.action_runner.storage_backend = backend
    deps.action_runner.execution_order = [HALTED, ORDINARY]
    deps.output_manager = MagicMock()
    deps.output_manager.resolve_correlated_input.return_value = None
    deps.skip_evaluator = MagicMock()
    deps.skip_evaluator.should_skip_action.return_value = False
    deps.batch_manager = MagicMock()
    return ActionExecutor(deps)


def _params(action_name: str) -> ActionRunParams:
    return ActionRunParams(
        action_name=action_name,
        action_idx=0,
        action_config={"kind": "llm"},
        is_last_action=False,
        start_time=datetime.now(),
    )


def _fail_through_the_executor(backend, state_manager, action_name, error) -> None:
    """Reach the halted state the way production does — via _handle_run_failure."""
    _executor(backend, state_manager)._handle_run_failure(_params(action_name), error)


def _node_row(backend, action_name) -> dict | None:
    rows = backend.get_disposition(action_name, record_id=NODE_LEVEL_RECORD_ID)
    return rows[0] if rows else None


def _coordinator(backend, state_manager, *, fresh: bool = False) -> AgentWorkflow:
    workflow = object.__new__(AgentWorkflow)
    workflow.config = SimpleNamespace(fresh=fresh)
    workflow.storage_backend = backend
    workflow.services = SimpleNamespace(core=SimpleNamespace(state_manager=state_manager))
    return workflow


class TestTheHaltIsRecorded:
    def test_a_policy_halt_is_marked_on_the_node_row(self, backend, state_manager):
        _fail_through_the_executor(backend, state_manager, HALTED, _halt_error())

        row = _node_row(backend, HALTED)
        assert row is not None
        assert row["disposition"] == DISPOSITION_FAILED
        assert row["detail"] == HALT_MARKER

    def test_the_human_message_is_still_the_reason(self, backend, state_manager):
        _fail_through_the_executor(backend, state_manager, HALTED, _halt_error())

        assert HALT_MESSAGE in _node_row(backend, HALTED)["reason"]

    def test_an_ordinary_failure_is_not_marked(self, backend, state_manager):
        _fail_through_the_executor(
            backend, state_manager, ORDINARY, RuntimeError("provider timed out")
        )

        assert _node_row(backend, ORDINARY)["detail"] != HALT_MARKER

    def test_an_error_that_did_not_raise_by_policy_is_not_marked(self, backend, state_manager):
        """return_last carries the same context key with a different value."""
        error = AgentActionsError("exhausted", context={"on_exhausted": "return_last"})
        _fail_through_the_executor(backend, state_manager, ORDINARY, error)

        assert _node_row(backend, ORDINARY)["detail"] != HALT_MARKER

    def test_the_halt_survives_the_file_processing_wrapper(self, backend, state_manager):
        """Every action runs through process_files, which re-raises its own error.

        The policy lives on the original exception's context, so a marker read
        only from the outermost error is never written in production.
        """
        wrapped = DependencyError(
            "Action 'summarize_page_content': dbt_pages.json: Retry exhausted "
            "(Found 1 files but failed to process any.)",
            context={"action": HALTED, "files_found": 1},
            cause=_halt_error(),
        )
        _fail_through_the_executor(backend, state_manager, HALTED, wrapped)

        assert _node_row(backend, HALTED)["detail"] == HALT_MARKER

    def test_an_unrelated_wrapped_failure_is_not_marked(self, backend, state_manager):
        wrapped = DependencyError(
            "Action 'author_stem': a.json: boom (Found 1 files but failed to process any.)",
            context={"action": ORDINARY, "files_found": 1},
            cause=RuntimeError("boom"),
        )
        _fail_through_the_executor(backend, state_manager, ORDINARY, wrapped)

        assert _node_row(backend, ORDINARY)["detail"] != HALT_MARKER


class TestTheStartupResetLeavesItAlone:
    def test_the_halted_action_keeps_its_failed_status(self, backend, state_manager):
        _fail_through_the_executor(backend, state_manager, HALTED, _halt_error())

        _coordinator(backend, state_manager)._reset_retryable_actions()

        assert state_manager.get_status(HALTED) == ActionStatus.FAILED

    def test_the_halted_action_keeps_its_evidence(self, backend, state_manager):
        _fail_through_the_executor(backend, state_manager, HALTED, _halt_error())

        _coordinator(backend, state_manager)._reset_retryable_actions()

        assert _node_row(backend, HALTED) is not None

    def test_an_ordinary_failure_is_still_reset(self, backend, state_manager):
        """The 'just run it again' ergonomics for transient failures must survive."""
        _fail_through_the_executor(
            backend, state_manager, ORDINARY, RuntimeError("provider timed out")
        )

        _coordinator(backend, state_manager)._reset_retryable_actions()

        assert state_manager.get_status(ORDINARY) == ActionStatus.PENDING
        assert _node_row(backend, ORDINARY) is None

    def test_one_halted_action_does_not_hold_back_the_others(self, backend, state_manager):
        _fail_through_the_executor(backend, state_manager, HALTED, _halt_error())
        _fail_through_the_executor(backend, state_manager, ORDINARY, RuntimeError("timeout"))

        _coordinator(backend, state_manager)._reset_retryable_actions()

        assert state_manager.get_status(HALTED) == ActionStatus.FAILED
        assert state_manager.get_status(ORDINARY) == ActionStatus.PENDING


class TestTheExecutorDoesNotReRunIt:
    """Status alone gates nothing — execute_action_sync has no FAILED branch."""

    def test_a_halted_action_is_not_executed(self, backend, state_manager):
        _fail_through_the_executor(backend, state_manager, HALTED, _halt_error())
        executor = _executor(backend, state_manager)

        result = executor.execute_action_sync(
            HALTED, action_idx=0, action_config={"kind": "llm"}, is_last_action=False
        )

        executor.deps.action_runner.run_action.assert_not_called()
        assert result.success is False
        assert result.status == ActionStatus.FAILED

    def test_an_ordinary_failed_action_is_still_executed(self, backend, state_manager):
        """Blocking every FAILED action would break ordinary retry."""
        _fail_through_the_executor(
            backend, state_manager, ORDINARY, RuntimeError("provider timed out")
        )
        executor = _executor(backend, state_manager)

        executor.execute_action_sync(
            ORDINARY, action_idx=1, action_config={"kind": "llm"}, is_last_action=True
        )

        executor.deps.action_runner.run_action.assert_called_once()


class TestFreshStillClearsIt:
    def test_a_fresh_run_is_the_documented_way_out(self, backend, state_manager, monkeypatch):
        _fail_through_the_executor(backend, state_manager, HALTED, _halt_error())
        workflow = _coordinator(backend, state_manager, fresh=True)
        cleared: list[str] = []
        monkeypatch.setattr(
            AgentWorkflow, "_clear_for_fresh_run", lambda self: cleared.append("cleared")
        )

        workflow._prepare_state(read_only=False)

        assert cleared == ["cleared"]
