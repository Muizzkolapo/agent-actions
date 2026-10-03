"""A batch collect pass stopped by an error, as the user meets it: what the provider is sent.

Two input files of one action, driven through the real pipeline, store, registry, status
file and reset. The collect pass writes the first file and is stopped before the second.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus
from tests.integration.test_batch_rerun_matches_online import (
    ACTION,
    UPSTREAM,
    Answerer,
    _Batch,
    _collect,
    rec,
)

ORDER = [UPSTREAM, ACTION]
INPUTS = {
    "page1.json": [rec("a1"), rec("a2")],
    "page2.json": [rec("b1"), rec("b2")],
}


def _submit(batch: _Batch, file: str) -> tuple[dict[str, Any], list[list[dict[str, Any]]]]:
    """One run's pass over one input file. Returns its config and what it sent."""
    batch.file = batch.stored_as = file
    batch._upstream_wrote(INPUTS[file])
    config, pipeline = batch._pipeline({}, ())
    before = len(batch.provider.submitted)
    with patch(
        "agent_actions.llm.batch.infrastructure.batch_client_resolver."
        "BatchClientResolver.get_for_config",
        return_value=batch.provider,
    ):
        batch._process(pipeline, INPUTS[file])
    assert batch.raised[-1] is None, batch.raised[-1]
    return config, batch.provider.submitted[before:]


def _collect_file(batch: _Batch, config: dict[str, Any], file: str, tasks: Any, run: int) -> None:
    job = SimpleNamespace(
        submitted=[tasks],
        vendor_type=batch.provider.vendor_type,
        prepare_tasks=batch.provider.prepare_tasks,
        submit_batch=batch.provider.submit_batch,
    )
    _collect(batch.backend, job, config, batch.out, file, run, Answerer())


def _next_run_resets(status_file, backend) -> None:
    """A new process: a state manager read from the file, and the reset a run starts with."""
    workflow = object.__new__(AgentWorkflow)
    state_manager = ActionStateManager(status_file, ORDER)
    workflow.services = SimpleNamespace(core=SimpleNamespace(state_manager=state_manager))
    workflow.storage_backend = backend
    workflow._reset_retryable_actions()


def _sent(submissions: list[list[dict[str, Any]]]) -> list[str]:
    return sorted(task["custom_id"] for tasks in submissions for task in tasks)


def test_a_file_collected_before_the_error_is_not_sent_again(tmp_path):
    status_file = tmp_path / ".agent_status.json"
    batch = _Batch(tmp_path, clears_batch_state=False)

    # Run 1 submits both files.
    config, first = _submit(batch, "page1.json")
    _, second = _submit(batch, "page2.json")
    assert _sent(first) == ["t-a1", "t-a2"]
    assert _sent(second) == ["t-b1", "t-b2"]

    # Run 2 finds both jobs finished, collects page1, and is stopped by an error.
    registry = BatchRegistryManager(batch.backend, ACTION)
    for file in INPUTS:
        registry.update_status(registry.get_batch_job(file).batch_id, BatchStatus.COMPLETED)
    stopped = ActionStateManager(status_file, ORDER)
    stopped.update_status(UPSTREAM, ActionStatus.COMPLETED)
    stopped.update_status(ACTION, ActionStatus.CHECKING_BATCH)
    _collect_file(batch, config, "page1.json", first[0], run=1)
    stopped.mark_running_as_failed()

    # Run 3 resets, then runs the action over both files.
    _next_run_resets(status_file, batch.backend)
    _, page1_again = _submit(batch, "page1.json")
    config, page2_again = _submit(batch, "page2.json")

    assert _sent(page1_again) == [], "page1 was collected and written, and is sent again"
    assert _sent(page2_again) == [], "page2's job is finished and waiting to be collected"

    # The file the error stopped short of is still there to collect.
    _collect_file(batch, config, "page2.json", second[0], run=2)
    assert batch.everything_held() == [
        "processed:a1:0@run1",
        "processed:a2:0@run1",
        "processed:b1:0@run2",
        "processed:b2:0@run2",
    ]
