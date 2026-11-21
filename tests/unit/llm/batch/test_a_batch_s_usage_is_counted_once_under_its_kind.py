"""Each batch a run reads is counted once, as calls of its kind, at the batch price.

A batch is counted where its results are retrieved, by what its registry entry says it
is: the first batch and a retry of it are the action's `main` calls, a repair round is
`repair`, and a side batch is its own kind (`judge`, or a kind the accounting has never
heard of). The count is kept under the batch's id, so a run that reads a batch an earlier
run already read adds nothing: a run that stops between reading a judge batch and saving
its state leaves the batch to be read again.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services import processing_recovery as pr
from agent_actions.llm.batch.services.side_batch import (
    register_side_requester,
    unregister_side_requester,
)
from agent_actions.llm.providers.usage_tracker import UsageLedger, accounting, stored_usage

from .judge_batch_world import (
    JudgingProvider,
    Run,
    answers,
    judge_rule,
    judged_config,
    value_in,
    verdict,
)
from .test_a_second_kind_of_side_call_runs_as_the_judge_does import (
    COPIES,
    Echo,
    EchoingProvider,
    _plain_config,
)
from .test_repair_deferral import ACTION

VALUES = {"r1": ["a"], "r2": ["b"]}
VOTES = 3
PER_REQUEST = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}


class Metered:
    """A provider whose every returned line reports `PER_REQUEST`."""

    def retrieve_results(self, batch_id, output_directory):
        results = super().retrieve_results(batch_id, output_directory)  # type: ignore[misc]
        for result in results:
            result.usage = dict(PER_REQUEST)
        return results


class MeteredJudge(Metered, JudgingProvider):
    pass


class MeteredEcho(Metered, EchoingProvider):
    pass


def _row(kind: str, calls: int, model: str = "test-model") -> dict:
    return {
        "kind": kind,
        "batch": True,
        "model": model,
        "calls": calls,
        "input_tokens": 10 * calls,
        "output_tokens": 2 * calls,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


def _to_the_end(run: Run) -> None:
    for _pass in range(6):
        if run.recovery_batch_returns() is not None:
            return
    pytest.fail("the file was never written")


def _judging(passed: bool = True) -> MeteredJudge:
    return MeteredJudge(lambda _prompt, _vote: verdict(passed, "judged"))


def test_a_judge_batch_is_counted_as_judge_calls_at_the_batch_price():
    run = Run(judged_config([judge_rule(votes=VOTES)], repair="none"), _judging())
    ledger = UsageLedger(ACTION)

    with accounting(ledger):
        run.main_batch_returns(answers(VALUES))
        _to_the_end(run)

    assert ledger.rows() == [_row("judge", len(VALUES) * VOTES)]
    assert run.online == [], "a judge call was made online"


def test_a_judge_batch_is_counted_under_the_model_its_rule_names():
    rule = judge_rule(votes=VOTES, model="judge-model")
    run = Run(judged_config([rule], repair="none"), _judging())
    ledger = UsageLedger(ACTION)

    with accounting(ledger):
        run.main_batch_returns(answers(VALUES))
        _to_the_end(run)

    assert {task["body"]["model"] for task in run.provider.submitted} == {"judge-model"}
    assert ledger.rows() == [_row("judge", len(VALUES) * VOTES, model="judge-model")]


def test_a_repair_round_is_counted_as_repair_calls_and_its_judge_batch_as_judge_calls():
    provider = MeteredJudge(
        lambda prompt, _vote: verdict(value_in(prompt) in (["good"], ["fixed"]), "judged"),
        repair=lambda _custom_id: {"options": ["fixed"]},
    )
    run = Run(judged_config([judge_rule()], repair="auto", max_iterations=3), provider)
    ledger = UsageLedger(ACTION)

    with accounting(ledger):
        run.main_batch_returns(answers({"r1": ["bad"], "r2": ["good"]}))
        _to_the_end(run)

    assert [name for name, _n in provider.batches] == [
        "f.json_judge_1",
        "f.json_repair_1",
        "f.json_judge_2",
    ]
    assert ledger.rows() == [_row("repair", 1), _row("judge", 2 + 1)]


def test_a_side_batch_of_a_kind_the_accounting_never_heard_of_is_counted_under_its_name():
    echo = Echo()
    register_side_requester(echo)
    try:
        run = Run(_plain_config(), MeteredEcho())
        ledger = UsageLedger(ACTION)

        with accounting(ledger):
            run.main_batch_returns(answers(VALUES))
            _to_the_end(run)
    finally:
        unregister_side_requester(echo.kind)

    assert ledger.rows() == [_row("echo", len(VALUES) * COPIES)]


def test_a_run_that_stops_after_reading_a_judge_batch_does_not_count_it_again_on_resume():
    """The state that says the batch was read is saved after the step that follows it."""
    run = Run(judged_config([judge_rule(votes=VOTES)], repair="none"), _judging())
    stopped = UsageLedger(ACTION, "run-1", run.backend)
    with accounting(stopped):
        run.main_batch_returns(answers(VALUES))
        judge_batch = run.live_entry().batch_id
        with (
            patch.object(pr, "check_and_submit_repair", side_effect=RuntimeError("stopped")),
            pytest.raises(RuntimeError, match="stopped"),
        ):
            run.recovery_batch_returns()
    assert run.live_entry().batch_id == judge_batch, "the judge batch is still the one to read"

    resumed = UsageLedger(ACTION, "run-2", run.backend)
    with accounting(resumed):
        assert run.recovery_batch_returns() == "/out.json"

    assert run.provider.read == [judge_batch, judge_batch], "the resume read the batch again"
    assert stopped.rows() == [_row("judge", len(VALUES) * VOTES)]
    assert resumed.rows() == []
    (entry,) = _usage_entries(run)
    assert (entry["batch_id"], entry["run_id"]) == (judge_batch, "run-1")
    assert entry["rows"] == [_row("judge", len(VALUES) * VOTES)]


def _usage_entries(run: Run) -> list[dict]:
    class Listing:
        load_metadata = staticmethod(run.backend.load_metadata)

        @staticmethod
        def list_metadata_prefix(prefix: str) -> list[str]:
            return sorted(key for key in run.backend.meta if key.startswith(prefix))

    return stored_usage(Listing)


def _entry(**recovery) -> BatchJobEntry:
    return BatchJobEntry(
        batch_id="b", status="completed", timestamp="t", provider="openai", **recovery
    )


@pytest.mark.parametrize(
    ("recovery", "kind"),
    [
        ({}, "main"),
        ({"recovery_type": "retry", "parent_file_name": "f.json"}, "main"),
        ({"recovery_type": "repair", "parent_file_name": "f.json"}, "repair"),
        ({"recovery_type": "side", "side_kind": "judge", "parent_file_name": "f.json"}, "judge"),
        ({"recovery_type": "side", "side_kind": "echo", "parent_file_name": "f.json"}, "echo"),
    ],
)
def test_a_batch_s_registry_entry_says_what_its_calls_are_counted_as(recovery, kind):
    assert BatchJobEntry.from_dict(_entry(**recovery).to_dict()).usage_kind == kind
