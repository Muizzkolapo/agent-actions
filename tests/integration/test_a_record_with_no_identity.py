"""A record that reaches an action without a source_guid has no identity, in either mode.

Every record is stamped where it is staged or by the action that produced it. The store,
the gate, a repair and ``agac retry --record`` all know it by that, so one that arrives
without it was made outside those rules: an edited upstream file, say. Online refuses it
at enrichment and records nothing. Batch recorded it under the id it was sent by, its
target_id, which nothing that selects records reads: ``agac retry`` named that failure,
cleared it, sent nothing, and the action read complete over the failed row it still held.

Driven as in ``test_batch_rerun_matches_online``: the pipeline, the store, the preparator,
submission, enrichment, the collector and finalize are the production objects.
"""

from __future__ import annotations

import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.cli.args import RetryCommandArgs
from agent_actions.cli.retry import RetryCommand
from agent_actions.errors import raised_by_terminal_failure
from agent_actions.processing.disposition_gate import positions_named_by_repair
from agent_actions.processing.invocation.result import InvocationResult
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from agent_actions.workflow.executor import ActionExecutor
from agent_actions.workflow.managers.state import ActionStatus
from tests.integration.test_batch_rerun_matches_online import (
    ACTION,
    PREPARED,
    SKIP,
    Answerer,
    RunMode,
    _Batch,
    _Mode,
    answers,
    rec,
)

EXTRA = {**SKIP, **PREPARED}


@pytest.fixture(autouse=True)
def _only_warnings_are_captured(caplog):
    caplog.set_level(logging.WARNING, logger="agent_actions")


def nameless(**fields: Any) -> dict[str, Any]:
    """n1 as the action above hands it on, less its source_guid; its target_id is t-n1."""
    row = rec("n1", keep=True, **fields)
    del row["source_guid"]
    return row


def answered() -> list[dict[str, Any]]:
    return [rec("a1", keep=True, topic="dbt"), nameless(topic="dbt")]


def unpreparable() -> list[dict[str, Any]]:
    """n1 has no topic, so its prompt cannot be rendered."""
    return [rec("a1", keep=True, topic="dbt"), nameless()]


def _recorded(mode: _Mode) -> dict[str, str]:
    return {row["record_id"]: row["disposition"] for row in mode.backend.get_disposition(ACTION)}


def _status(mode: _Mode) -> ActionStatus:
    """What the executor makes of the action once its run returns."""
    executor = ActionExecutor(
        SimpleNamespace(action_runner=SimpleNamespace(storage_backend=mode.backend))
    )
    return executor._resolve_completion_status(ACTION)


class _Model:
    """What online asks: the answer names the record it was asked about."""

    def invoke(self, prepared: Any, context: Any) -> InvocationResult:
        return InvocationResult.immediate(
            response={"answer": f"{prepared.source_guid}:0@run1"}, executed=True
        )


class _Online(_Mode):
    """Online with its real strategy; only the model is replaced."""

    run_mode = RunMode.ONLINE

    def run(self, inputs: list[dict[str, Any]]) -> list[str]:
        self._upstream_wrote(inputs)
        _config, pipeline = self._pipeline(EXTRA, ())
        pipeline._online_strategy._invocation_strategy = _Model()
        self._process(pipeline, inputs)
        return answers(self.held())


def _submit(batch: _Batch, inputs: list[dict[str, Any]]) -> None:
    """A batch run that submits and stops there, as one does before the next run collects."""
    batch._upstream_wrote(inputs)
    _config, pipeline = batch._pipeline(EXTRA, ())
    with patch(
        "agent_actions.llm.batch.infrastructure.batch_client_resolver."
        "BatchClientResolver.get_for_config",
        return_value=batch.provider,
    ):
        batch._process(pipeline, inputs)
    assert batch.raised[-1] is None and batch.provider.submitted, "nothing was submitted"


@pytest.mark.parametrize(
    "inputs, answer",
    [
        (unpreparable(), Answerer()),
        (answered(), Answerer({"t-n1": "fail"})),
        (answered(), Answerer()),
    ],
    ids=["it_cannot_be_prepared", "the_provider_fails_it", "it_is_answered"],
)
def test_batch_records_nothing_under_the_target_id_of_a_record_with_no_source_guid(
    tmp_path, inputs, answer
):
    """No failure, no success, and no deferred mark left behind once it is collected.

    A target_id is minted afresh by any run whose input has none, and nothing that
    selects a record reads it.
    """
    batch = _Batch(tmp_path)

    batch.run(1, inputs, answer=answer, extra=EXTRA)

    assert batch.raised[-1] is None
    assert "t-n1" not in _recorded(batch)


def test_every_failure_agac_retry_names_is_one_its_repair_can_select(tmp_path):
    """A repair selects records by source_guid. A failure it cannot select is one the
    retry clears and never repairs, and the action then reads complete.

    a1 fails as well, so there is a failure to name; a2 is answered.
    """
    batch = _Batch(tmp_path)
    inputs = [*unpreparable(), rec("a2", keep=True, topic="dbt")]
    batch.run(1, inputs, answer=Answerer({"a1": "fail"}), extra=EXTRA)

    named = batch.failures()

    assert [name for name in named if not positions_named_by_repair(inputs, {name})] == []
    assert named == ["a1"]


@pytest.mark.parametrize("inputs", [answered(), unpreparable()], ids=["answered", "not_preparable"])
def test_batch_holds_and_records_what_online_does_for_a_record_with_no_source_guid(
    tmp_path, inputs
):
    """Online refuses it at enrichment: a failed row with no identity, and no disposition.

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


def test_a_batch_none_of_whose_records_has_a_source_guid_fails_the_action_as_online_does(
    tmp_path,
):
    """Recorded nowhere, its records leave no disposition to read the action failed by,
    so it read complete and the action below went on. Online's breaker stops it there.

    Raised once the file is written, as a batch's other halts are, and the executor
    records the action failed on it rather than leaving it to re-poll a collected batch.
    """
    (tmp_path / "online").mkdir()
    (tmp_path / "batch").mkdir()
    online = _Online(tmp_path / "online")
    batch = _Batch(tmp_path / "batch")
    inputs = [nameless(topic="dbt")]

    online.run(inputs)
    with pytest.raises(RuntimeError, match="produced 0 successful records") as halt:
        batch.run(1, inputs, extra=EXTRA)

    assert f"RuntimeError: {halt.value}" == online.raised[-1]
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


def test_abandoning_a_batch_marks_no_failure_under_the_target_id_of_a_record_with_no_source_guid(
    tmp_path,
):
    """`--abandon-in-flight` marks what waits on the batch failed so a later retry can
    reach it. Marked under its target_id, that is a failure the later retry clears and
    does not repair."""
    batch = _Batch(tmp_path)
    _submit(batch, answered())

    RetryCommand(RetryCommandArgs(agent="w", abandon_in_flight=True))._settle_batches_in_flight(
        batch.backend, [ACTION]
    )

    assert batch.failures() == ["a1"]
