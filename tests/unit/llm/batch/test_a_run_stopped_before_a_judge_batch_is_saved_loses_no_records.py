"""A run that stops after a judge batch is registered and before its state is saved loses no
records.

The registration replaces the file's live repair round, so the next run finds the
judge batch with the state of the round before. It must not write the file from
that state; the file is processed again from its main batch.
"""

from unittest.mock import patch

import pytest

from agent_actions.llm.batch.services import processing_recovery as pr

from .judge_batch_world import (
    JudgingProvider,
    Run,
    answers,
    judge_rule,
    judged_config,
    value_in,
    verdict,
)

VALUES = {"r1": ["bad"], "r2": ["good"]}


class _Stopped(BaseException):
    """The process ending: nothing after it runs."""


def _stopped_after_registering_judge_2() -> tuple[Run, JudgingProvider]:
    provider = JudgingProvider(
        lambda prompt, _vote: verdict(value_in(prompt) in (["good"], ["fixed"]), "judged"),
        repair=lambda _custom_id: {"options": ["fixed"]},
    )
    run = Run(judged_config([judge_rule()], repair="auto", max_iterations=3), provider)
    assert run.main_batch_returns(answers(VALUES)) is False
    assert run.recovery_batch_returns() is None, "judge batch 1 sent no repair round"
    assert run.live_entry().recovery_type == "repair"

    with (
        patch.object(pr.RecoveryStateManager, "save", side_effect=_Stopped),
        pytest.raises(_Stopped),
    ):
        run.recovery_batch_returns()
    return run, provider


def test_the_window_leaves_the_judge_batch_registered_over_the_state_of_the_round_before():
    run, provider = _stopped_after_registering_judge_2()

    assert [name for name, _n in provider.batches][-1] == "f.json_judge_2"
    entry = run.live_entry()
    assert (entry.recovery_type, entry.side_kind, entry.recovery_attempt) == ("side", "judge", 2)
    assert run.state().side_attempts["judge"] == 1


def test_the_next_run_does_not_write_the_file_from_the_old_state():
    run, provider = _stopped_after_registering_judge_2()
    judge_2 = run.live_entry().batch_id

    assert run.recovery_batch_returns() is None
    assert run.finalized is None, "the file was written from the state of the round before"
    assert run.live_entry() is None, "the judge batch still holds the file"
    assert judge_2 not in provider.read, "the batch was read against the wrong state"


def _with_a_side_round_in_the_state(run: Run) -> None:
    """The stale state still names a side round, as one stopped mid-round would."""
    import json

    from .judge_batch_world import ACTION, FILE

    key = f"recovery_state:{ACTION}:{FILE}"
    stored = json.loads(run.backend.meta[key])
    stored.update(
        side_kind="judge",
        side_requests={"j_old_0": "old"},
        side_waiting=[{"custom_id": "r1"}],
        side_resumes="repair",
    )
    run.backend.meta[key] = json.dumps(stored)


def test_the_drop_says_what_happened_and_resets_the_side_round_of_the_state(caplog):
    run, _provider = _stopped_after_registering_judge_2()
    _with_a_side_round_in_the_state(run)
    judge_2 = run.live_entry().batch_id

    with caplog.at_level("WARNING"):
        run.recovery_batch_returns()

    message = " ".join(record.getMessage() for record in caplog.records)
    assert "No recovery state" not in message
    assert f"Judge batch {judge_2}" in message
    assert "stopped before it saved" in message
    assert "billed" in message
    state = run.state()
    assert state is not None
    assert (state.side_attempts["judge"], state.side_requests, state.side_waiting) == (2, {}, [])
    assert (state.side_kind, state.side_resumes) == (None, None)


def test_the_file_processed_again_from_its_main_batch_keeps_every_record():
    run, provider = _stopped_after_registering_judge_2()
    run.recovery_batch_returns()

    assert run.main_batch_returns(answers(VALUES)) is False
    out = None
    for _pass in range(6):
        out = run.recovery_batch_returns()
        if out is not None:
            break

    assert out == "/out.json"
    assert run.online == []
    assert {cid: v["overall_pass"] for cid, v in run.verdicts().items()} == {
        "r1": True,
        "r2": True,
    }
