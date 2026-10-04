"""`on_empty: error` in a batch, on the path a run takes.

The halt is raised by the finaliser once the file is written. Between there and the
run are the loop over the action's batch files and the executor's handling of a
failed batch check, and either can lose it.
"""

from __future__ import annotations

import logging
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import DependencyError
from agent_actions.errors.processing import EmptyOutputError
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services.collect import _empty_output_halt
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.record.reasons import EMPTY_OUTPUT
from agent_actions.workflow.executor import ActionExecutor


def _halt() -> EmptyOutputError:
    empty = MagicMock(skip_reason=EMPTY_OUTPUT, source_guid="a1")
    answered = MagicMock(skip_reason=None, source_guid="a2")
    ctx = MagicMock(agent_config={"on_empty": "error"}, agent_name="summarize")
    halt = _empty_output_halt([empty, answered], ctx)
    assert halt is not None
    return halt


def _service_over(files: dict[str, Exception | str]) -> BatchProcessingService:
    """A service whose registry holds *files*, each collecting to a path or raising."""
    manager = MagicMock()
    manager.get_all_jobs.return_value = {
        name: BatchJobEntry(batch_id=f"b_{name}", status="completed", timestamp="t", provider="p")
        for name in files
    }
    manager.get_batch_job.side_effect = manager.get_all_jobs.return_value.get
    service = BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=lambda name: manager,
        workflow_name="summarize",
        storage_backend=MagicMock(),
    )
    service._provider_status = MagicMock(return_value=BatchStatus.COMPLETED)

    def collect(*, file_name, **kwargs):
        outcome = files[file_name]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    service._process_single_batch_file = MagicMock(side_effect=collect)
    service._fail_abandoned_records = MagicMock()
    return service


def test_the_halt_leaves_the_loop_over_the_action_s_files():
    service = _service_over({"one.json": _halt(), "two.json": "/out/two.json"})

    with pytest.raises(EmptyOutputError, match="on_empty=error"):
        service.process_all_batch_results("/out", {"on_empty": "error"}, action_name="summarize")


def test_the_records_of_the_file_it_stopped_on_are_not_marked_failed():
    """The file is written and its records hold their own dispositions by then. Marked
    failed as abandoned, the answered ones lose a success and the empty one its reason."""
    service = _service_over({"one.json": _halt()})

    with pytest.raises(EmptyOutputError):
        service.process_all_batch_results("/out", {"on_empty": "error"}, action_name="summarize")

    service._fail_abandoned_records.assert_not_called()


def test_any_other_processing_error_still_costs_only_its_own_file():
    from agent_actions.errors import ProcessingError

    service = _service_over(
        {"one.json": ProcessingError("this file cannot be read"), "two.json": "/out/two.json"}
    )

    written = service.process_all_batch_results("/out", {}, action_name="summarize").written

    assert written == ["/out/two.json"]
    assert service._fail_abandoned_records.call_count == 1


@pytest.mark.parametrize("wrapped", [False, True])
def test_the_executor_records_the_action_as_failed(wrapped):
    """Re-raised, as a polling failure is, the action stays checking its batch and
    every later run collects the same file and stops the same way."""
    halt: Exception = _halt()
    if wrapped:
        outer = DependencyError("file processing failed")
        outer.__cause__ = halt
        halt = outer
    executor = object.__new__(ActionExecutor)
    executor.deps = MagicMock()
    executor._handle_run_failure = MagicMock(return_value="recorded")

    result = executor._handle_batch_exception("summarize", 0, {}, datetime.now(), halt)

    assert result == "recorded"


def test_a_polling_failure_is_still_re_raised():
    executor = object.__new__(ActionExecutor)
    executor.deps = MagicMock()
    executor._handle_run_failure = MagicMock()

    with pytest.raises(OSError, match="provider unreachable"):
        executor._handle_batch_exception(
            "summarize", 0, {}, datetime.now(), OSError("provider unreachable")
        )

    executor._handle_run_failure.assert_not_called()


def test_a_second_halt_for_the_same_file_is_said_and_not_dropped_silently(caplog):
    from agent_actions.errors import exhaustion_halt
    from agent_actions.llm.batch.services.collect import _halt_for

    first = exhaustion_halt("Retry exhausted for a3")
    empty = MagicMock(skip_reason=EMPTY_OUTPUT, source_guid="a1")
    ctx = MagicMock(agent_config={"on_empty": "error"}, agent_name="summarize")
    ctx.pending_exhaustion = first

    with caplog.at_level(logging.WARNING, logger="agent_actions"):
        raised = _halt_for([empty], ctx)

    assert raised is first
    assert "empty output" in caplog.text
