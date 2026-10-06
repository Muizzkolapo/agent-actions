"""A record that reaches an action without a source_guid has no identity, in either mode.

Every record is stamped where it is staged or by the action that produced it. The store,
the gate, a repair and ``agac retry --record`` all know it by that, so one that arrives
without it was made outside those rules: an edited upstream file, say. Both modes refuse
it once the guard has decided it, before its prompt is rendered or sent, store it as a
failed row and record nothing for it. Batch recorded it under the id it was sent by, its
target_id, which nothing that selects records reads: ``agac retry`` named that failure,
cleared it, sent nothing, and the action read complete over the failed row it still held.
A batch an earlier release sent can still hold such a record, and collecting it refuses
the record the same way.

Driven as in ``test_batch_rerun_matches_online``: the pipeline, the store, the preparator,
submission, enrichment, the collector and finalize are the production objects.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.retry import RetryCommand
from agent_actions.errors import raised_by_terminal_failure
from agent_actions.errors.processing import EmptyOutputError
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.retry import BatchRetryService
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.disposition_gate import positions_named_by_repair
from agent_actions.processing.invocation.result import InvocationResult
from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.storage.backend import DISPOSITION_DEFERRED, NODE_LEVEL_RECORD_ID
from agent_actions.workflow.executor import ActionExecutor
from agent_actions.workflow.managers.state import ActionStatus
from tests.integration.test_a_collect_pass_leaves_collected_files_alone import _Action
from tests.integration.test_batch_rerun_matches_online import (
    ACTION,
    FILE,
    FILTER,
    PREPARED,
    SKIP,
    UPSTREAM,
    Answerer,
    RunMode,
    _Batch,
    _collect,
    _Mode,
    answers,
    rec,
)

EXTRA = {**SKIP, **PREPARED}


@pytest.fixture(autouse=True)
def _only_warnings_are_captured(caplog):
    caplog.set_level(logging.WARNING, logger="agent_actions")


def nameless(keep: bool = True, **fields: Any) -> dict[str, Any]:
    """n1 as the action above hands it on, less its source_guid; its target_id is t-n1."""
    row = rec("n1", keep=keep, **fields)
    del row["source_guid"]
    return row


def answered() -> list[dict[str, Any]]:
    return [rec("a1", keep=True, topic="dbt"), nameless(topic="dbt")]


def unpreparable() -> list[dict[str, Any]]:
    """n1 has no topic, so its prompt cannot be rendered."""
    return [rec("a1", keep=True, topic="dbt"), nameless()]


def skipped() -> list[dict[str, Any]]:
    return [rec("a1", keep=True, topic="dbt"), nameless(keep=False, topic="dbt")]


def _recorded(mode: _Mode) -> dict[str, str]:
    return {row["record_id"]: row["disposition"] for row in mode.backend.get_disposition(ACTION)}


def _status(mode: _Mode) -> ActionStatus:
    """What the executor makes of the action once its run returns."""
    executor = ActionExecutor(
        SimpleNamespace(action_runner=SimpleNamespace(storage_backend=mode.backend))
    )
    return executor._resolve_completion_status(ACTION)


def _failed_row(mode: _Mode) -> dict[str, Any]:
    """The one failed row, less its state history: batch's also carries the transition
    preparation made, as the row of every record batch fails to prepare does."""
    (row,) = [row for row in mode.held() if row.get("_state") == "failed"]
    return {key: value for key, value in row.items() if key != "_state_history"}


class _Model:
    """What online asks, answered as batch's harness answers it: by source_guid, or by
    target_id where the record has none."""

    def __init__(self, answer: Answerer) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def invoke(self, prepared: Any, context: Any) -> InvocationResult:
        label = prepared.source_guid or prepared.source_snapshot["target_id"]
        self.asked.append(label)
        said = self.answer(label, 1)
        return InvocationResult.immediate(
            response=said if len(said) != 1 else said[0], executed=True
        )


class _Online(_Mode):
    """Online with its real strategy; only the model is replaced."""

    run_mode = RunMode.ONLINE

    def run(
        self,
        inputs: list[dict[str, Any]],
        answer: Answerer | None = None,
        extra: dict[str, Any] = EXTRA,
    ) -> list[str]:
        self._upstream_wrote(inputs)
        _config, pipeline = self._pipeline(extra, ())
        self.model = _Model(answer or Answerer())
        pipeline._online_strategy._invocation_strategy = self.model
        self._process(pipeline, inputs)
        return answers(self.held())


def _traced(mode: _Mode) -> list[Any]:
    """Whose prompt was rendered for the model: a trace is written as it is."""
    return [trace["source_guid"] for trace in mode.backend.get_prompt_traces(ACTION)]


def _submit(batch: _Batch, inputs: list[dict[str, Any]]) -> dict[str, Any]:
    """A batch run that submits and stops there, as one does before the next run collects.

    Returns the action's config, for the collect.
    """
    batch._upstream_wrote(inputs)
    config, pipeline = batch._pipeline(EXTRA, ())
    with patch(
        "agent_actions.llm.batch.infrastructure.batch_client_resolver."
        "BatchClientResolver.get_for_config",
        return_value=batch.provider,
    ):
        batch._process(pipeline, inputs)
    assert batch.raised[-1] is None and batch.provider.submitted, "nothing was submitted"
    return config


@contextmanager
def _sent_as_an_earlier_release() -> Iterator[None]:
    """Prepare as a release before this one did: a record with no source_guid is sent.

    Such a batch can still be out when this release collects it.
    """
    with patch.object(TaskPreparer, "_require_identity"):
        yield


@pytest.mark.parametrize(
    "inputs, answer, extra",
    [
        (unpreparable(), Answerer(), EXTRA),
        (answered(), Answerer({"t-n1": "fail"}), EXTRA),
        (answered(), Answerer(), EXTRA),
        (answered(), Answerer({"t-n1": "exhaust"}), EXTRA),
        (answered(), Answerer({"t-n1": "empty object"}), EXTRA),
        (answered(), Answerer({"t-n1": "empty object"}), {**EXTRA, "on_empty": "skip"}),
        (skipped(), Answerer(), EXTRA),
    ],
    ids=[
        "it_cannot_be_prepared",
        "the_provider_fails_it",
        "it_is_answered",
        "its_retries_run_out",
        "its_answer_is_empty",
        "its_empty_answer_is_skipped",
        "the_guard_skips_it",
    ],
)
def test_batch_records_nothing_under_the_target_id_of_a_record_with_no_source_guid(
    tmp_path, caplog, inputs, answer, extra
):
    """No failure, no success, and no deferred mark left behind once it is collected.

    A target_id is minted afresh by any run whose input has none, and nothing that
    selects a record reads it. Such a record is no longer sent, but a batch an earlier
    release sent can hold it in any of these shapes, each built apart, so each is asked.
    """
    batch = _Batch(tmp_path)

    with _sent_as_an_earlier_release():
        batch.run(1, inputs, answer=answer, extra=extra)

    assert batch.raised[-1] is None
    assert _recorded(batch) == {"a1": "success"}
    assert "Failed to write disposition" not in caplog.text


def _placeholder_for(custom_id: str):
    """Collect with *custom_id*'s line unreadable: the parser mints a placeholder for it."""
    finalize = BatchProcessingService._finalize_batch_output

    def collect(self, *, batch_results, **kwargs):
        kept = [result for result in batch_results if result.custom_id != custom_id]
        kept.append(
            BatchResult(custom_id="error_line_2", content=None, success=False, error="unreadable")
        )
        return finalize(self, batch_results=kept, **kwargs)

    return patch.object(BatchProcessingService, "_finalize_batch_output", collect)


@pytest.mark.parametrize("unnamed", ["no_source_guid", "a_parser_placeholder"])
def test_every_failure_agac_retry_names_is_one_its_repair_can_select(tmp_path, unnamed):
    """A repair selects records by source_guid. A failure it cannot select is one the
    retry clears and never repairs, and the action then reads complete.

    a1 fails as well, so there is a failure to name; a2 is answered.
    """
    batch = _Batch(tmp_path)
    if unnamed == "no_source_guid":
        inputs = [*unpreparable(), rec("a2", keep=True, topic="dbt")]
        batch.run(1, inputs, answer=Answerer({"a1": "fail"}), extra=EXTRA)
    else:
        inputs = [rec(guid, keep=True, topic="dbt") for guid in ("a1", "a2", "a3")]
        with _placeholder_for("t-a3"):
            batch.run(1, inputs, answer=Answerer({"a1": "fail"}), extra=EXTRA)

    named = batch.failures()

    assert [name for name in named if not positions_named_by_repair(inputs, {name})] == []
    assert named == ["a1"]


@pytest.mark.parametrize("inputs", [answered(), unpreparable()], ids=["answered", "not_preparable"])
def test_batch_holds_and_records_what_online_does_for_a_record_with_no_source_guid(
    tmp_path, inputs
):
    """Both refuse it: a failed row with no identity, and no disposition.

    So the action reads complete in both, with the refusal in the run log and the row.
    """
    (tmp_path / "online").mkdir()
    (tmp_path / "batch").mkdir()
    online = _Online(tmp_path / "online")
    batch = _Batch(tmp_path / "batch")

    online_held = online.run(inputs)
    batch_held = batch.run(1, inputs, extra=EXTRA)

    assert (batch.raised[-1], online.raised[-1]) == (None, None)
    assert online_held == ["failed:None", "processed:a1:0@run1"]
    assert batch_held == online_held
    assert _recorded(batch) == _recorded(online) == {"a1": "success"}
    assert _status(batch) == _status(online) == ActionStatus.COMPLETED


@pytest.mark.parametrize("inputs", [answered(), unpreparable()], ids=["answered", "not_preparable"])
def test_the_failed_row_of_a_record_with_no_source_guid_keeps_what_it_arrived_with(
    tmp_path, inputs
):
    """Its target_id and what the action above said are all that tell a reader which
    record it was, and the reason names it by that target_id."""
    (tmp_path / "online").mkdir()
    (tmp_path / "batch").mkdir()
    online = _Online(tmp_path / "online")
    batch = _Batch(tmp_path / "batch")

    online.run(inputs)
    batch.run(1, inputs, extra=EXTRA)

    row = _failed_row(online)
    assert _failed_row(batch) == row
    assert (row["source_guid"], row["target_id"], sorted(row["content"])) == (
        None,
        "t-n1",
        [UPSTREAM, ACTION],
    )
    assert row["_tombstone_reason"].startswith(
        f"Record t-n1 reached '{ACTION}' without a source_guid"
    )


_DELETED = object()


@pytest.mark.parametrize("lost", [_DELETED, None, ""], ids=["deleted", "null", "empty"])
def test_a_record_with_no_source_guid_is_neither_prepared_nor_sent_in_either_mode(tmp_path, lost):
    """It was refused only once its answer came back: paid for, and the answer thrown
    away. The prompt trace written as its prompt was rendered was the one sign left that
    it had been sent. An edit can drop the field or blank it, and a blank one names no
    record either."""
    (tmp_path / "online").mkdir()
    (tmp_path / "batch").mkdir()
    online = _Online(tmp_path / "online")
    batch = _Batch(tmp_path / "batch")
    inputs = answered()
    if lost is not _DELETED:
        inputs[1]["source_guid"] = lost

    online.run(inputs)
    batch.run(1, inputs, extra=EXTRA)

    assert online.model.asked == ["a1"]
    assert [task["custom_id"] for task in batch.provider.submitted[-1]] == ["t-a1"]
    assert _traced(online) == _traced(batch) == ["a1"]


def test_a_record_with_no_source_guid_is_refused_whatever_its_answer_would_have_been(tmp_path):
    """An answer of several rows was kept, each row given an identity of its own, while
    the record it answered still had none, so no run could carry it."""
    (tmp_path / "online").mkdir()
    (tmp_path / "batch").mkdir()
    online = _Online(tmp_path / "online")
    batch = _Batch(tmp_path / "batch")
    answer = Answerer({"t-n1": 2})

    online_held = online.run(answered(), answer=answer)
    batch_held = batch.run(1, answered(), answer=answer, extra=EXTRA)

    assert online_held == batch_held == ["failed:None", "processed:a1:0@run1"]
    assert _recorded(online) == _recorded(batch) == {"a1": "success"}


def test_a_record_with_no_source_guid_does_not_stop_a_batch_at_its_preflight(tmp_path):
    """The preflight renders the first prompts to catch a broken template before anything
    is sent, and stops the action at the first that fails. It rendered this one, whose
    prompt cannot be rendered, so one record with no identity stopped the whole action."""
    batch = _Batch(tmp_path)

    held = batch.run(1, [nameless(), rec("a1", keep=True, topic="dbt")], extra=EXTRA)

    assert batch.raised[-1] is None
    assert held == ["failed:None", "processed:a1:0@run1"]


def test_the_preflight_still_stops_a_broken_template_behind_a_record_with_no_source_guid(
    tmp_path,
):
    """Passing over the refused record, it renders the next prompt, which is what it is
    there to check: a1 has no topic."""
    batch = _Batch(tmp_path)

    batch.run(1, [nameless(topic="dbt"), rec("a1", keep=True)], extra=EXTRA)

    assert "references undefined variables" in batch.raised[-1]
    assert batch.provider.submitted == []


@pytest.mark.parametrize(
    "guard, held",
    [
        (FILTER, ["processed:a1:0@run1"]),
        (SKIP, ["failed:None", "processed:a1:0@run1"]),
    ],
    ids=["filtered", "skipped"],
)
def test_the_guard_decides_a_record_with_no_source_guid_before_it_is_refused(tmp_path, guard, held):
    """Online's guard runs above its strategy and batch's inside preparation; the refusal
    comes after both. A record the guard filters leaves nothing, and one it skips is
    refused at enrichment, in both modes."""
    (tmp_path / "online").mkdir()
    (tmp_path / "batch").mkdir()
    online = _Online(tmp_path / "online")
    batch = _Batch(tmp_path / "batch")
    extra = {**guard, **PREPARED}

    online_held = online.run(skipped(), extra=extra)
    batch_held = batch.run(1, skipped(), extra=extra)

    assert online_held == batch_held == held
    assert _recorded(online) == _recorded(batch) == {"a1": "success"}


def test_a_batch_none_of_whose_records_has_a_source_guid_fails_the_action_as_online_does(
    tmp_path,
):
    """Recorded nowhere, its records leave no disposition to read the action failed by.
    Refused before anything is sent, the run sends nothing and raises online's breaker
    once the file is written."""
    (tmp_path / "online").mkdir()
    (tmp_path / "batch").mkdir()
    online = _Online(tmp_path / "online")
    batch = _Batch(tmp_path / "batch")
    inputs = [nameless(topic="dbt")]

    online.run(inputs)
    batch.run(1, inputs, extra=EXTRA)

    assert batch.provider.submitted == []
    assert batch.raised[-1] == online.raised[-1]
    assert "produced 0 successful records" in batch.raised[-1]
    assert answers(batch.held()) == ["failed:None"]


def test_collecting_such_records_from_an_earlier_release_fails_the_action_as_online_does(
    tmp_path,
):
    """Sent by an earlier release, they left no disposition either, so the action read
    complete and the action below went on. Online's breaker stops it there.

    Raised once the file is written, as a batch's other halts are, and the executor
    records the action failed on it rather than leaving it to re-poll a collected batch.
    """
    (tmp_path / "online").mkdir()
    (tmp_path / "batch").mkdir()
    online = _Online(tmp_path / "online")
    batch = _Batch(tmp_path / "batch")
    inputs = [nameless(topic="dbt")]

    online.run(inputs)
    with (
        _sent_as_an_earlier_release(),
        pytest.raises(RuntimeError, match="produced 0 successful records") as halt,
    ):
        batch.run(1, inputs, extra=EXTRA)

    assert raised_by_terminal_failure(halt.value)
    assert answers(batch.held()) == ["failed:None"]
    executor = ActionExecutor(
        SimpleNamespace(
            action_runner=SimpleNamespace(storage_backend=batch.backend),
            state_manager=MagicMock(),
        )
    )
    failed = executor._handle_batch_exception(ACTION, 1, {}, datetime.now(), halt.value)
    assert failed.status == ActionStatus.FAILED
    assert batch.failures() == [NODE_LEVEL_RECORD_ID]


def test_the_on_empty_error_halt_names_a_record_with_no_source_guid_by_its_target_id(tmp_path):
    """Named by its source_guid, it was named "None". Only a batch an earlier release
    sent can still hold such a record's answer."""
    batch = _Batch(tmp_path)

    with (
        _sent_as_an_earlier_release(),
        pytest.raises(EmptyOutputError, match=r"\(on_empty=error\): t-n1$"),
    ):
        batch.run(
            1,
            answered(),
            answer=Answerer({"t-n1": "empty object"}),
            extra={**EXTRA, "on_empty": "error"},
        )


def test_collecting_clears_a_deferred_mark_left_under_the_target_id_by_an_earlier_release(
    tmp_path,
):
    """A batch an earlier release submitted marked the record deferred under its target_id.
    Collection now records nothing for it, so that mark was never cleared, and every
    collect after warned of it as orphaned."""
    batch = _Batch(tmp_path)
    with _sent_as_an_earlier_release():
        config = _submit(batch, answered())
    batch.backend.set_disposition(ACTION, "t-n1", DISPOSITION_DEFERRED)

    _collect(batch.backend, batch.provider, config, batch.out, Path(batch.file).name, 1, Answerer())

    assert _recorded(batch) == {"a1": "success"}


def test_abandoning_a_batch_marks_no_failure_under_the_target_id_of_a_record_with_no_source_guid(
    tmp_path,
):
    """`--abandon-in-flight` marks what waits on the batch failed so a later retry can
    reach it. Marked under its target_id, that is a failure the later retry clears and
    does not repair. A batch an earlier release sent can still hold it."""
    batch = _Batch(tmp_path)
    with _sent_as_an_earlier_release():
        _submit(batch, answered())
    command = RetryCommand(RetryCommandArgs(agent="w", abandon_in_flight=True))

    command._settle_batches_in_flight(batch.backend, command._batches_owed(batch.backend, [ACTION]))

    assert batch.failures() == ["a1"]


def test_a_record_with_no_source_guid_does_not_keep_a_retry_from_a_failed_batch_action(tmp_path):
    """A retry narrows a failed batch action whose batches hold an answer or a failure for
    every record they were sent. The refused record holds neither, and no run gives it
    one: counted, it refused the retry for good, while online's action, its every record
    reached and failed, is narrowed. Only a batch an earlier release sent can hold it."""
    batch = _Batch(tmp_path)

    with (
        _sent_as_an_earlier_release(),
        pytest.raises(RuntimeError, match="produced 0 successful records"),
    ):
        batch.run(1, answered(), answer=Answerer({"a1": "fail"}), extra=EXTRA)

    assert batch.failures() == ["a1"]
    assert RetryCommand._unfinished_as(batch.backend, ACTION, ActionStatus.FAILED) is None


@pytest.mark.parametrize(
    "lost, sent_again",
    [({"n1"}, []), ({"a2", "n1"}, [{"t-a2"}])],
    ids=["alone", "beside_another"],
)
def test_a_retry_does_not_send_again_a_record_with_no_source_guid_the_provider_lost(
    tmp_path, lost, sent_again
):
    """Preparation refuses it, so a retry for it alone would admit nothing and fail the
    collect pass on every run, and beside another record it would be counted lost again
    every round. Left out, it is collected unanswered and refused at enrichment.

    Only a batch an earlier release sent can hold such a record.
    """
    inputs = [*answered(), rec("a2", keep=True, topic="dbt")]
    action = _Action(tmp_path, {**PREPARED, "retry": {"enabled": True, "max_attempts": 2}})
    action.provider.withheld = lost
    action.upstream_holds({FILE: inputs})
    with _sent_as_an_earlier_release():
        action.process(FILE, inputs)

    with patch.object(
        BatchRetryService,
        "submit_retry_batch",
        autospec=True,
        side_effect=BatchRetryService.submit_retry_batch,
    ) as retry:
        action.collect()

    assert [call.kwargs["missing_ids"] for call in retry.call_args_list] == sent_again
    assert "failed:None" in action.held(FILE)
