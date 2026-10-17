"""`agac retry --abandon-in-flight` abandons an owed batch once, and says so once.

With no failed record recorded, the retry abandons the batch to find its failures, then
reached the batch again on its way to the plan and abandoned it a second time, reporting
0 records waiting.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.retry import RetryCommand
from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage.backend import DISPOSITION_DEFERRED
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ACTION = "summarize"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


def _owe_a_batch_in_flight(backend) -> None:
    BatchRegistryManager(backend, ACTION).save_batch_job(
        "f.json",
        BatchJobEntry(
            batch_id="b1", status="submitted", timestamp="t", provider="mock", file_name="f.json"
        ),
    )
    sent = {"t-1": {"target_id": "t-1", "source_guid": "sg-1"}}
    BatchContextMetadata.set_filter_status(sent["t-1"], FilterStatus.INCLUDED)
    BatchContextManager.save_batch_context_map(backend, ACTION, sent, "f.json")
    backend.set_disposition(ACTION, "sg-1", DISPOSITION_DEFERRED, reason="batch_queued")


def test_the_abandon_message_prints_once(backend, tmp_path):
    _owe_a_batch_in_flight(backend)
    state_manager = ActionStateManager(tmp_path / ".agent_status.json", [ACTION])
    state_manager.update_status(ACTION, ActionStatus.FAILED)
    command = RetryCommand(RetryCommandArgs(agent="wf", abandon_in_flight=True))
    command.console = MagicMock()

    found = command._failures_when_none_is_recorded(backend, state_manager, [ACTION], [])
    assert found and [r["record_id"] for r in found[ACTION]] == ["sg-1"]
    # What `execute` does next, on its way to the plan.
    command._settle_batches_in_flight(backend, command._batches_owed(backend, [ACTION]))

    printed = [str(c.args[0]) for c in command.console.print.call_args_list]
    abandoning = [p for p in printed if "Abandoning" in p]
    assert len(abandoning) == 1, printed
    assert "1 record(s) waiting" in abandoning[0]
