"""A collect error leaves a failure `agac retry` can see, and retry does not call it done.

Under batch, a collect pass can raise an ordinary error on one file. The action reads
`failed`, a finished batch stays uncollected, and no record is failed. `retry` looked
only at failed and exhausted records, found none, and printed a green "Nothing to
retry" while a file stayed unanswered.
"""

from datetime import datetime
from unittest.mock import MagicMock

import click
import pytest

from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.retry import RetryCommand
from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_FAILED,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ACTION = "summarize"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


@pytest.fixture
def state_manager(tmp_path):
    return ActionStateManager(tmp_path / ".agent_status.json", [ACTION])


def _executor(backend, state_manager) -> ActionExecutor:
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = state_manager
    deps.action_runner = MagicMock()
    deps.action_runner.storage_backend = backend
    deps.action_runner.execution_order = [ACTION]
    deps.output_manager = MagicMock()
    deps.skip_evaluator = MagicMock()
    deps.batch_manager = MagicMock()
    return ActionExecutor(deps)


def _command(**flags) -> RetryCommand:
    command = RetryCommand(RetryCommandArgs(agent="wf", **flags))
    command.console = MagicMock()
    return command


def _printed(command: RetryCommand) -> str:
    return " ".join(str(c.args[0]) for c in command.console.print.call_args_list)


def _owe_a_finished_batch(backend, *, collected_at: str | None = None) -> None:
    """A finished batch whose results nobody wrote, over one record still waiting on it."""
    BatchRegistryManager(backend, ACTION).save_batch_job(
        "f.json",
        BatchJobEntry(
            batch_id="b1",
            status="completed",
            timestamp="t",
            provider="mock",
            file_name="f.json",
            collected_at=collected_at,
        ),
    )
    sent = {"t-1": {"target_id": "t-1", "source_guid": "sg-1"}}
    BatchContextMetadata.set_filter_status(sent["t-1"], FilterStatus.INCLUDED)
    BatchContextManager.save_batch_context_map(backend, ACTION, sent, "f.json")
    backend.set_disposition(ACTION, "sg-1", DISPOSITION_DEFERRED, reason="batch_queued")


class TestACollectErrorLeavesAFailureRetryCanSee:
    def test_the_row_the_executor_writes_is_found_by_retry_and_is_not_a_halt(
        self, backend, state_manager
    ):
        executor = _executor(backend, state_manager)
        executor.deps.batch_manager.handle_batch_agent.side_effect = RuntimeError(
            "the provider dropped the connection"
        )

        with pytest.raises(RuntimeError, match="dropped the connection"):
            executor._handle_batch_check(ACTION, 0, {"kind": "llm"}, datetime.now())

        found = RetryCommand._find_failures(backend, [ACTION])
        assert [r["record_id"] for r in found[ACTION]] == [NODE_LEVEL_RECORD_ID]
        assert found[ACTION][0]["detail"] is None
        assert "dropped the connection" in found[ACTION][0]["reason"]


class TestRetryDoesNotCallAnOwedBatchOrAFailedActionDone:
    def test_a_finished_uncollected_batch_is_refused_with_the_remedy(self, backend, state_manager):
        _owe_a_finished_batch(backend)
        state_manager.update_status(ACTION, ActionStatus.FAILED)

        with pytest.raises(click.ClickException, match="Collect them first"):
            _command()._failures_when_none_is_recorded(backend, state_manager, [ACTION], [])

    def test_a_refusal_leaves_the_registry_and_the_waiting_record_untouched(
        self, backend, state_manager
    ):
        _owe_a_finished_batch(backend)
        state_manager.update_status(ACTION, ActionStatus.FAILED)

        with pytest.raises(click.ClickException):
            _command()._failures_when_none_is_recorded(backend, state_manager, [ACTION], [])

        entry = BatchRegistryManager(backend, ACTION).get_batch_job("f.json")
        assert entry is not None and entry.collected_at is None
        rows = backend.get_disposition(ACTION, record_id="sg-1")
        assert [r["disposition"] for r in rows] == [DISPOSITION_DEFERRED]

    def test_a_dry_run_reports_the_refusal_and_says_nothing_is_to_retry_for_nothing(
        self, backend, state_manager
    ):
        _owe_a_finished_batch(backend)
        state_manager.update_status(ACTION, ActionStatus.FAILED)
        command = _command(dry_run=True)

        result = command._failures_when_none_is_recorded(backend, state_manager, [ACTION], [])

        assert result is None
        assert "would be refused" in _printed(command)

    def test_abandoning_hands_back_the_records_it_stranded(self, backend, state_manager):
        _owe_a_finished_batch(backend)
        state_manager.update_status(ACTION, ActionStatus.FAILED)

        result = _command(abandon_in_flight=True)._failures_when_none_is_recorded(
            backend, state_manager, [ACTION], []
        )

        assert result is not None
        assert [r["record_id"] for r in result[ACTION]] == ["sg-1"]
        assert result[ACTION][0]["disposition"] == DISPOSITION_FAILED

    def test_a_collected_batch_owes_nothing_so_the_failed_action_is_rerun_in_full(
        self, backend, state_manager
    ):
        _owe_a_finished_batch(backend, collected_at="2026-10-16T10:00:00+00:00")
        state_manager.update_status(ACTION, ActionStatus.FAILED, error_message="boom")

        result = _command()._failures_when_none_is_recorded(backend, state_manager, [ACTION], [])

        assert result is not None
        assert [r["record_id"] for r in result[ACTION]] == [NODE_LEVEL_RECORD_ID]

    def test_a_batch_waiting_to_be_collected_is_not_a_failure_when_nothing_failed(
        self, backend, state_manager
    ):
        _owe_a_finished_batch(backend)
        state_manager.update_status(ACTION, ActionStatus.BATCH_SUBMITTED)

        result = _command()._failures_when_none_is_recorded(backend, state_manager, [ACTION], [])

        assert result == {}

    def test_a_failed_action_with_no_failed_record_and_no_batch_fails_as_a_whole(
        self, backend, state_manager
    ):
        state_manager.update_status(ACTION, ActionStatus.FAILED, error_message="disk I/O error")

        result = _command()._failures_when_none_is_recorded(backend, state_manager, [ACTION], [])

        # The failure its run could not store, as its own handler stores one.
        assert result == RetryCommand._find_failures(backend, [ACTION])
        assert result is not None
        [row] = result[ACTION]
        assert row["record_id"] == NODE_LEVEL_RECORD_ID
        assert row["disposition"] == DISPOSITION_FAILED
        assert row["reason"] == "disk I/O error"

    def test_a_dry_run_plans_over_that_failure_and_stores_nothing(self, backend, state_manager):
        state_manager.update_status(ACTION, ActionStatus.FAILED, error_message="disk I/O error")

        result = _command(dry_run=True)._failures_when_none_is_recorded(
            backend, state_manager, [ACTION], []
        )

        assert result is not None
        assert [r["reason"] for r in result[ACTION]] == ["disk I/O error"]
        assert backend.get_disposition(ACTION) == []

    def test_a_failure_with_no_message_is_still_named_as_the_actions_own(
        self, backend, state_manager
    ):
        state_manager.update_status(ACTION, ActionStatus.FAILED)

        result = _command()._failures_when_none_is_recorded(backend, state_manager, [ACTION], [])

        assert result is not None
        assert "failed before any of its records" in result[ACTION][0]["reason"]

    def test_a_clean_workflow_still_has_nothing_to_retry(self, backend, state_manager):
        state_manager.update_status(ACTION, ActionStatus.COMPLETED)

        result = _command()._failures_when_none_is_recorded(backend, state_manager, [ACTION], [])

        assert result == {}
