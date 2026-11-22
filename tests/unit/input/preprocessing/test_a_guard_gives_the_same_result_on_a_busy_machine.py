"""A guard gives the same result for the same record on a busy machine and an idle one.

The time limit counts the evaluation, not its wait for one of the shared workers. A
guard that still runs out of time does not pass its record: the record fails with the
clause and the reason, so the operator can find it and `agac retry` runs it again.
"""

import threading
import time
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import GuardNotEvaluatedError
from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.input.preprocessing.filtering.guard_filter import (
    FilterItemRequest,
    GuardFilter,
)
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.logging.events.validation_events import GuardEvaluationTimeoutEvent
from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.storage.backend import DISPOSITION_FAILED
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

CLAUSE = "a1.n > 0"


@contextmanager
def _guards_that_take(seconds: float):
    """Every guard evaluation takes *seconds* before it gives its answer."""
    guard_filter = GuardFilter()
    evaluate = guard_filter._evaluate_guard_condition

    def slow(*args: Any) -> bool:
        time.sleep(seconds)
        return evaluate(*args)

    guard_filter._evaluate_guard_condition = slow  # type: ignore[method-assign]
    evaluator = GuardEvaluator(guard_filter)
    try:
        with patch(
            "agent_actions.input.preprocessing.filtering.evaluator.get_guard_evaluator",
            return_value=evaluator,
        ):
            yield evaluator
    finally:
        guard_filter.shutdown()


def _guard(on_false: str = "filter", passthrough_on_error: bool = True, **more: Any) -> dict:
    return {
        "clause": CLAUSE,
        "behavior": on_false,
        "passthrough_on_error": passthrough_on_error,
        **more,
    }


def _record() -> dict:
    return {"source_guid": "G0", "content": {"a1": {"n": 1}}}


def _config(guard: dict) -> dict:
    return {
        "agent_type": "a2",
        "name": "a2",
        "granularity": "record",
        "context_scope": {"observe": ["a1.n"]},
        "prompt": "Say {{ a1.n }}.",
        "json_mode": False,
        "model_vendor": "openai",
        "model_name": "gpt-4",
        "dependencies": ["a1"],
        "guard": guard,
    }


def test_a_simple_guard_behind_a_busy_pool_gives_its_result():
    guard_filter = GuardFilter()
    release = threading.Event()
    try:
        for _ in range(4):
            guard_filter.executor.submit(release.wait, 2.0)

        result = guard_filter.filter_item(
            FilterItemRequest(data={"n": 1}, condition="n > 0", timeout=1)
        )
    finally:
        release.set()
        guard_filter.shutdown()

    assert (result.success, result.matched, result.error) == (True, True, None)


@pytest.mark.parametrize("passthrough_on_error", [True, False])
@pytest.mark.parametrize("on_false", ["filter", "skip"])
def test_a_guard_that_runs_out_of_time_fails_its_record_with_the_reason(
    on_false, passthrough_on_error
):
    events: list = []
    with (
        _guards_that_take(1.0) as evaluator,
        patch(
            "agent_actions.input.preprocessing.filtering.evaluator.fire_event",
            side_effect=events.append,
        ),
        pytest.raises(GuardNotEvaluatedError) as raised,
    ):
        evaluator.evaluate(
            {"a1": {"n": 1}},
            _guard(on_false, passthrough_on_error, timeout=0.2),
            record_id="G0",
        )

    message = str(raised.value)
    assert CLAUSE in message and "G0" in message and "0.2s" in message
    (event,) = [e for e in events if isinstance(e, GuardEvaluationTimeoutEvent)]
    assert (event.guard_clause, event.timeout_seconds, event.record_id) == (CLAUSE, 0.2, "G0")
    assert event.data["record_id"] == "G0"
    assert "action_name" in event.data


def test_a_warn_guard_that_runs_out_of_time_still_runs_its_record():
    with _guards_that_take(1.0) as evaluator:
        result = evaluator.evaluate({"a1": {"n": 0}}, _guard("warn", timeout=0.2), record_id="G0")

    assert result.should_execute is True


def test_a_record_whose_guard_runs_out_of_time_is_not_prepared():
    context = PreparationContext(
        agent_config=_config(_guard(timeout=0.2)), agent_name="a2", agent_indices={"a1": 0, "a2": 1}
    )

    with _guards_that_take(1.0), pytest.raises(GuardNotEvaluatedError, match="G0"):
        TaskPreparer().prepare(_record(), context)


def test_a_carried_record_whose_guard_runs_out_of_time_is_looked_at_again():
    preparator = BatchTaskPreparator(action_indices={"a1": 0, "a2": 1}, dependency_configs={})

    with _guards_that_take(1.0):
        again = preparator.turned_away(_config(_guard(timeout=0.2)), [_record()])

    assert again == {"G0"}


def test_an_online_record_whose_guard_runs_out_of_time_is_failed_with_the_reason(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    backend.initialize()
    strategy = OnlineLLMStrategy(
        agent_config=_config(_guard(timeout=0.2)),
        agent_name="a2",
        invocation_strategy=MagicMock(),
    )
    context = ProcessingContext(
        agent_config=_config(_guard(timeout=0.2)),
        agent_name="a2",
        agent_indices={"a1": 0, "a2": 1},
        storage_backend=backend,
    )

    with _guards_that_take(1.0):
        (result,) = strategy.invoke([_record()], context)

    assert result.status == ProcessingStatus.FAILED
    strategy._invocation_strategy.invoke.assert_not_called()
    (row,) = backend.get_disposition("a2", record_id="G0", disposition=DISPOSITION_FAILED)
    assert CLAUSE in row["reason"] and "0.2s" in row["reason"]


def test_a_file_mode_record_whose_guard_runs_out_of_time_is_failed_alone():
    from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

    records = [_record(), {"source_guid": "G1", "content": {"a1": {"n": 2}}}]

    with _guards_that_take(1.0):
        passing, skipped, _originals, filtered, failed = prefilter_by_guard(
            records, _config(_guard(timeout=0.2)), "a2", agent_indices={"a1": 0, "a2": 1}
        )

    assert (passing, skipped, filtered) == ([], [], [])
    assert [record["source_guid"] for record, _error in failed] == ["G0", "G1"]
    assert all(isinstance(error, GuardNotEvaluatedError) for _record, error in failed)


@patch("agent_actions.prompt.formatter.PromptFormatter.get_raw_prompt", return_value="prompt")
@patch.object(BatchTaskPreparator, "_run_preflight_validation")
def test_a_batch_record_whose_guard_runs_out_of_time_is_failed_with_the_reason(
    _preflight, _prompt, tmp_path
):
    backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    backend.initialize()
    provider = MagicMock()
    provider.prepare_tasks.return_value = []
    preparator = BatchTaskPreparator(
        action_indices={"a1": 0, "a2": 1}, dependency_configs={}, storage_backend=backend
    )

    with _guards_that_take(1.0):
        prepared = preparator.prepare_tasks(
            agent_config=_config(_guard(timeout=0.2)),
            data=[{**_record(), "target_id": "t0"}],
            provider=provider,
            output_directory=str(tmp_path),
        )

    assert prepared.stats.error_items == 1
    assert prepared.stats.included_items == 0
    (row,) = backend.get_disposition("a2", record_id="G0", disposition=DISPOSITION_FAILED)
    assert CLAUSE in row["reason"] and "0.2s" in row["reason"]


def test_a_guard_given_more_time_than_its_evaluation_takes_gives_its_result():
    context = PreparationContext(
        agent_config=_config(_guard(timeout=3)), agent_name="a2", agent_indices={"a1": 0, "a2": 1}
    )

    with _guards_that_take(1.0):
        prepared = TaskPreparer().prepare(_record(), context)

    assert prepared.guard_status == GuardStatus.PASSED
