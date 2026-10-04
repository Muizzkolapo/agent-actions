"""A batch run with nothing left to send stores what a run that sends stores.

When the guard, the action above or preparation leaves nothing to send, the run writes
the file itself. Built apart from the collector, its rows lost the tracking each record
carries and no record got a disposition, so a skipped record still read as answered, a
failure with no identity read as nothing at all, and every filtered record went
unrecorded.

Driven through the real pipeline, store and collector; only the provider is fake.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from agent_actions.errors import exhaustion_halt
from agent_actions.expectations.service import ExpectationConfigurationError
from agent_actions.input.preprocessing.staging import initial_pipeline
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.services import submission
from agent_actions.logging.core.manager import EventManager
from agent_actions.logging.events import BatchCompleteEvent
from agent_actions.output.writer import FileWriter
from agent_actions.processing.invocation.result import InvocationResult
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.lifecycle_read import reset_for_downstream
from agent_actions.record.state import RecordState
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from agent_actions.workflow.executor import ActionExecutor
from agent_actions.workflow.managers.state import ActionStatus
from tests.integration.test_a_collect_pass_leaves_collected_files_alone import _Action
from tests.integration.test_batch_rerun_matches_online import (
    ACTION,
    FILTER,
    SKIP,
    UPSTREAM,
    _Batch,
    _FirstStageBatch,
    _Online,
    answers,
    rec,
)


@pytest.fixture(autouse=True)
def _only_warnings_are_captured(caplog):
    caplog.set_level(logging.WARNING, logger="agent_actions")


FIRST_STAGE_SKIP = {"guard": {"clause": "source.keep == true", "behavior": "skip"}}

# A prompt the record must hold `topic` to render: without it, preparation fails it.
NEEDS_TOPIC = {"prompt": f"Write a question about {{{{ {UPSTREAM}.topic }}}}."}


def handed(guid: str, **fields: Any) -> dict[str, Any]:
    """An input as the store hands it to the action below: reset to active, history kept."""
    row = rec(guid, **fields)
    row["version_correlation_id"] = f"vc-{guid}"
    RecordEnvelope.transition(row, RecordState.PROCESSED, UPSTREAM, "success")
    reset_for_downstream([row], action_name=UPSTREAM)
    return row


def blocked(guid: str) -> dict[str, Any]:
    """An input the action above failed, which this one never judges."""
    row = rec(guid, keep=True, topic="dbt")
    row["version_correlation_id"] = f"vc-{guid}"
    RecordEnvelope.transition(row, RecordState.FAILED, UPSTREAM, "provider error")
    return row


def _held_back() -> list[dict[str, Any]]:
    """Five guard skips first, so preparation's sample renders; then one record the
    action above failed, and one that cannot be prepared."""
    return [
        *(handed(f"k{n}", keep=False, topic="dbt") for n in range(1, 6)),
        blocked("b1"),
        handed("p1", keep=True),
    ]


def _rows(batch: _Batch, leaving_out: str = "") -> dict[str, tuple[Any, ...]]:
    held = {}
    for row in batch.held():
        if row["source_guid"] == leaving_out:
            continue
        held[row["source_guid"]] = (
            row.get("_state"),
            row.get("parent_source_guid"),
            row.get("version_correlation_id"),
            (row.get("metadata") or {}).get("reason"),
            row.get("_tombstone_reason"),
            [entry["action"] for entry in row.get("_state_history") or []],
            sorted(key for key in row.get("metadata") or {} if key.startswith("skipped_by")),
        )
    return held


def _dispositions(backend: Any, leaving_out: str = "") -> dict[str, tuple[Any, ...]]:
    return {
        row["record_id"]: (
            row["disposition"],
            row.get("reason"),
            row.get("detail"),
            row.get("input_snapshot") is not None,
        )
        for row in backend.get_disposition(ACTION)
        if row["record_id"] not in (NODE_LEVEL_RECORD_ID, leaving_out)
    }


def _status(backend: Any) -> ActionStatus:
    """What the executor makes of the action once its run returns."""
    executor = ActionExecutor(
        SimpleNamespace(action_runner=SimpleNamespace(storage_backend=backend))
    )
    return executor._resolve_completion_status(ACTION)


def _batch(tmp_path: Path, name: str, file: str = "page.json") -> _Batch:
    (tmp_path / name).mkdir()
    return _Batch(tmp_path / name, file)


def test_a_run_with_nothing_to_send_stores_each_record_as_a_run_that_sends_does(tmp_path):
    quiet = _batch(tmp_path, "quiet")
    sending = _batch(tmp_path, "sending")

    quiet.run(1, _held_back(), extra={**SKIP, **NEEDS_TOPIC})
    sending.run(
        1, [*_held_back(), handed("a1", keep=True, topic="dbt")], extra={**SKIP, **NEEDS_TOPIC}
    )

    assert (quiet.sent, sending.sent) == ([[]], [["a1"]])
    assert _rows(quiet) == _rows(sending, leaving_out="a1")
    assert _dispositions(quiet.backend) == _dispositions(sending.backend, leaving_out="a1")


def test_the_rows_keep_what_the_action_above_gave_them(tmp_path):
    """Version merge correlates on it, and lineage reads the parent from it."""
    quiet = _batch(tmp_path, "quiet")

    quiet.run(1, _held_back(), extra={**SKIP, **NEEDS_TOPIC})

    for guid, (_state, parent, correlation, *_rest, flags) in _rows(quiet).items():
        assert (parent, correlation, flags) == ("S", f"vc-{guid}", []), guid


def test_each_record_held_back_is_recorded_as_a_run_that_sends_records_it(tmp_path):
    quiet = _batch(tmp_path, "quiet")

    quiet.run(1, _held_back(), extra={**SKIP, **NEEDS_TOPIC})

    dispositions = _dispositions(quiet.backend)
    assert {guid: dispositions[guid][:2] for guid in ("k1", "b1")} == {
        "k1": ("unprocessed", "guard_skip"),
        "b1": ("unprocessed", "upstream_unprocessed"),
    }


class _Answers:
    """The online model: every prompt it is given is answered."""

    def invoke(self, prepared: Any, context: Any) -> InvocationResult:
        return InvocationResult.immediate(response={"answer": "ok"}, executed=True)


def _online_failure(tmp_path: Path, inputs: list[dict[str, Any]]) -> tuple[Any, ...]:
    """What online records for p1, preparing every prompt for real."""
    (tmp_path / "online").mkdir()
    online = _Online(tmp_path / "online")
    online._upstream_wrote(inputs)
    _config, pipeline = online._pipeline({**SKIP, **NEEDS_TOPIC}, ())
    pipeline._online_strategy._invocation_strategy = _Answers()
    online._process(pipeline, copy.deepcopy(inputs))
    return _dispositions(online.backend)["p1"]


def test_a_record_that_cannot_be_prepared_keeps_its_error_on_both_batch_paths(tmp_path):
    """Online records the error itself. A batch that sent something recorded only
    that preparation failed, and one that sent nothing kept no detail."""
    sent = [*_held_back(), handed("a1", keep=True, topic="dbt")]
    quiet = _batch(tmp_path, "quiet")
    sending = _batch(tmp_path, "sending")

    quiet.run(1, _held_back(), extra={**SKIP, **NEEDS_TOPIC})
    sending.run(1, sent, extra={**SKIP, **NEEDS_TOPIC})

    online = _online_failure(tmp_path, sent)
    disposition, reason, detail, _snapshot = online
    assert (disposition, "topic" in reason, detail) == ("failed", True, reason)
    assert {
        "nothing sent": _dispositions(quiet.backend)["p1"],
        "a1 sent": _dispositions(sending.backend)["p1"],
    } == {"nothing sent": online, "a1 sent": online}
    for batch in (quiet, sending):
        (row,) = [row for row in batch.held() if row["source_guid"] == "p1"]
        assert (row["metadata"]["reason"], row["_tombstone_reason"]) == ("prep_failed",) * 2


def test_every_record_filtered_with_nothing_to_send_is_recorded_and_the_action_skipped(
    tmp_path,
):
    """Online and a run that sends record each one filtered; here none was."""
    batch = _batch(tmp_path, "quiet")

    held = batch.run(1, [handed("f1", keep=False), handed("f2", keep=False)], extra=FILTER)

    assert held == []
    assert {
        guid: disposition[:2] for guid, disposition in _dispositions(batch.backend).items()
    } == {"f1": ("filtered", "guard_filter"), "f2": ("filtered", "guard_filter")}
    assert batch.backend.has_disposition(ACTION, "passthrough", record_id=NODE_LEVEL_RECORD_ID)
    assert _status(batch.backend) == ActionStatus.SKIPPED


def test_an_action_whose_guard_now_filters_every_record_holds_nothing_and_is_skipped(tmp_path):
    """Its answers from before are for records the guard now excludes. Carried, the
    action reads complete and the actions below go on reading them."""
    batch = _batch(tmp_path, "quiet")
    batch.run(1, [handed("a1", keep=True), handed("a2", keep=True)], extra=FILTER)

    held = batch.run(
        2, [handed("a1", keep=False), handed("a2", keep=False)], extra=FILTER, reset=True
    )

    assert held == []
    assert _status(batch.backend) == ActionStatus.SKIPPED


def test_an_expect_block_that_cannot_be_resolved_stops_a_first_stage_run_with_nothing_to_send(
    tmp_path,
):
    """As it stops one that sends, once collected: the block is resolved to collect the
    run either way. Below the first stage, building the action's pipeline resolves it
    first, and `agac run` refuses such a block before any action runs."""
    batch = _FirstStageBatch(tmp_path)

    with pytest.raises(ExpectationConfigurationError, match="bare expect"):
        batch.run(1, [{"item": "s1", "keep": False}], {**FIRST_STAGE_SKIP, "expect": {}})


def test_an_answer_whose_record_comes_back_skipped_is_not_read_as_done(tmp_path):
    """a2 is answered, leaves, and comes back for the guard to skip while nothing else
    is sent. Its `success` stood over the skip, so the gate carried the skip for good
    and a2 was never sent again once the guard passed it."""
    batch = _batch(tmp_path, "quiet")
    batch.run(1, [handed("a1", keep=True), handed("a2", keep=True)], extra=SKIP)
    batch.run(2, [handed("a1", keep=True), handed("a3", keep=True)], extra=SKIP)

    batch.run(3, [handed("a1", keep=True), handed("a2", keep=False)], extra=SKIP)

    assert _dispositions(batch.backend)["a2"][:2] == ("unprocessed", "guard_skip")

    held = batch.run(4, [handed("a1", keep=True), handed("a2", keep=True)], extra=SKIP)

    assert batch.sent == [["a1", "a2"], ["a3"], [], ["a2"]]
    assert held == ["processed:a1:0@run1", "processed:a2:0@run4"]


def _nameless_failure() -> list[dict[str, Any]]:
    """Five guard skips, so preparation's sample renders, and n1: no source_guid, and
    no topic for its prompt."""
    nameless = handed("n1", keep=True)
    del nameless["source_guid"]
    return [*(handed(f"k{n}", keep=False, topic="dbt") for n in range(1, 6)), nameless]


def test_a_failure_with_no_identity_of_its_own_fails_the_action(tmp_path):
    """Stored failed with no disposition, it left the action reading complete. It is
    recorded under the target id the batch keys it by."""
    batch = _batch(tmp_path, "quiet")

    batch.run(1, _nameless_failure(), extra={**SKIP, **NEEDS_TOPIC})

    assert _dispositions(batch.backend)["t-n1"][0] == "failed"
    assert _status(batch.backend) == ActionStatus.FAILED


def test_a_retry_clears_a_failure_with_no_identity_without_repairing_it(tmp_path):
    """What `agac retry` does today: it names the failure by its target id, but a repair
    selects records by source_guid, so nothing is sent and the action reads complete
    over the failed row it still holds."""
    batch = _batch(tmp_path, "quiet")
    batch.run(1, _nameless_failure(), extra={**SKIP, **NEEDS_TOPIC})
    named = batch.failures()

    held = batch.run(2, _nameless_failure(), extra={**SKIP, **NEEDS_TOPIC}, retry=named)

    assert (named, batch.sent[-1], batch.raised[-1]) == (["t-n1"], [], None)
    assert "failed:t-n1" in held
    assert batch.failures() == []
    assert _status(batch.backend) == ActionStatus.COMPLETED


def test_a_run_with_nothing_to_send_leaves_the_batch_before_it_alone(tmp_path):
    """No batch was sent, so none is completed, collected or reported; what a
    finalize does to the registry and recovery state belongs to a batch."""
    (tmp_path / "quiet").mkdir()
    batch = _Batch(tmp_path / "quiet", clears_batch_state=False)
    earlier = BatchJobEntry(
        batch_id="batch-0",
        status=BatchStatus.FAILED,
        timestamp="t0",
        provider="openai",
        file_name="page.json",
    )
    BatchRegistryManager(batch.backend, ACTION).save_batch_job("page.json", earlier)
    RecoveryStateManager.save(batch.backend, ACTION, "page.json", RecoveryState(retry_attempt=1))
    fired: list[Any] = []

    with patch.object(EventManager, "fire", lambda _manager, event: fired.append(event)):
        held = batch.run(1, [handed("k1", keep=False)], extra=SKIP)

    assert held == ["guard_skipped:k1"]
    assert [event for event in fired if isinstance(event, BatchCompleteEvent)] == []
    assert BatchRegistryManager(batch.backend, ACTION).get_all_jobs() == {"page.json": earlier}
    assert RecoveryStateManager.load(batch.backend, ACTION, "page.json") == RecoveryState(
        retry_attempt=1
    )


def test_a_halt_decided_while_collecting_is_raised_once_the_file_is_written(tmp_path):
    """As finalize raises it. None can be decided with no results today, and raised
    first, one would take the file with it."""
    batch = _batch(tmp_path, "quiet")
    halt = exhaustion_halt("Retry exhausted for k1")
    collect, write = submission.collect_batch_rows, submission.write_batch_file
    order: list[str] = []

    def collecting(*args: Any, **kwargs: Any) -> Any:
        rows, stats, _none = collect(*args, **kwargs)
        order.append("collected")
        return rows, stats, halt

    def writing(*args: Any, **kwargs: Any) -> Any:
        order.append("written")
        return write(*args, **kwargs)

    with (
        patch.object(submission, "collect_batch_rows", collecting),
        patch.object(submission, "write_batch_file", writing),
    ):
        held = batch.run(1, [handed("k1", keep=False)], extra=SKIP)

    assert order == ["collected", "written"]
    assert batch.raised == [f"{type(halt).__name__}: {halt}"]
    assert held == ["guard_skipped:k1"]


def test_a_file_in_a_subdirectory_is_written_under_its_one_name_when_nothing_is_sent(
    tmp_path,
):
    batch = _batch(tmp_path, "quiet", "sub/page.json")

    held = batch.run(1, [handed("k1", keep=False)], extra=SKIP)

    assert batch.backend.list_target_files(ACTION) == ["sub/page.json"]
    assert held == ["guard_skipped:k1"]
    assert _dispositions(batch.backend)["k1"][:2] == ("unprocessed", "guard_skip")


def test_a_first_stage_run_with_nothing_to_send_is_written_once_and_recorded(tmp_path):
    """The caller wrote it by hand; the run now writes it as one that sends does."""
    batch = _FirstStageBatch(tmp_path)

    with patch.object(initial_pipeline, "FileWriter", wraps=FileWriter) as written_by_caller:
        batch.run(
            1, [{"item": "s1", "keep": False}, {"item": "s2", "keep": False}], FIRST_STAGE_SKIP
        )

    assert written_by_caller.call_count == 0
    assert batch.backend.list_target_files(ACTION) == ["page.json"]
    rows = batch.backend.read_target_for_rewrite(ACTION, "page.json")
    assert [row["metadata"].get("reason") for row in rows] == ["guard_skip", "guard_skip"]
    assert (
        sorted(_dispositions(batch.backend).values())
        == [("unprocessed", "guard_skip", None, False)] * 2
    )
    (node,) = batch.backend.get_disposition(ACTION, record_id=NODE_LEVEL_RECORD_ID)
    assert (node["disposition"], node["reason"]) == ("passthrough", "All records tombstoned")


def test_a_file_with_nothing_to_send_keeps_this_runs_rows_through_the_collect_pass(tmp_path):
    """page1 sends nothing while page2 is sent: the collect pass that follows must not
    put page1 back as its spent batch left it."""
    action = _Action(tmp_path)
    action.run({"page1.json": [rec("a1", keep=True)], "page2.json": [rec("b1", keep=True)]})

    action.run(
        {
            "page1.json": [rec("a3", keep=False)],
            "page2.json": [rec("b1", keep=True), rec("b2", keep=True)],
        }
    )

    assert action.held("page1.json") == ["guard_skipped:a3"]
    assert _dispositions(action.backend)["a3"][:2] == ("unprocessed", "guard_skip")
    assert answers(action.backend.read_target_for_rewrite(ACTION, "page2.json")) == [
        "processed:b1@batch-2",
        "processed:b2@batch-3",
    ]
