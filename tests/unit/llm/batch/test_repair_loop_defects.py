"""The repair loop's interactions with the machinery it shares.

Repair reuses the graduated pool, the recovery state and the exhaustion policy
that reprompt already uses. Sharing them is the point — but each is a place the
two loops can quietly stand on each other.
"""

from typing import Any

import pytest

from agent_actions.expectations.service import ExpectationService, ExpectationsExhaustedError
from agent_actions.expectations.types import Suite
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.evaluation import EvaluationLoop
from agent_actions.processing.evaluation.strategies import ExpectationStrategy, ValidationStrategy

SUITE = Suite(
    name="s",
    expectations=[{"id": "positive", "type": "expression", "condition": "score > 0"}],
)


def _strategy(**kwargs: Any) -> ExpectationStrategy:
    return ExpectationStrategy(
        ExpectationService(suite=SUITE, **{"repair": "auto", "max_iterations": 2, **kwargs})
    )


def _failing() -> BatchResult:
    return BatchResult(custom_id="r1", content={"score": -5}, success=True)


class TestGraduationIsPerStrategy:
    """One loop's graduation must not excuse a record from another loop's checks.

    `check_and_submit_reprompt` tags every record that passed validation, and the
    repair loop is handed the same objects. A flag that does not name its owner
    lets a record that failed its expectations skip evaluation entirely — no
    repair, and no verdict, because nothing downstream validates under a repair
    policy.
    """

    def test_a_record_reprompt_graduated_is_still_judged_by_expectations(self):
        result = _failing()
        validation = ValidationStrategy(
            validation_func=lambda c: True, feedback_message="m", validation_name="validation"
        )
        EvaluationLoop(validation).tag_graduated([result])

        _graduated, still_failing, _ = EvaluationLoop(_strategy()).split([result])
        assert [r.custom_id for r in still_failing] == ["r1"]

    def test_a_record_this_loop_graduated_is_not_re_judged(self):
        result = BatchResult(custom_id="r1", content={"score": 5}, success=True)
        strategy = _strategy()
        loop = EvaluationLoop(strategy)
        graduated, _still, _ = loop.split([result])
        loop.tag_graduated(graduated)

        again, still_failing, _ = loop.split([result])
        assert [r.custom_id for r in again] == ["r1"]
        assert still_failing == []

    def test_a_record_skipped_by_another_loops_tag_still_gets_a_verdict(self):
        result = _failing()
        EvaluationLoop(
            ValidationStrategy(
                validation_func=lambda c: True, feedback_message="m", validation_name="validation"
            )
        ).tag_graduated([result])

        strategy = _strategy()
        graduated, still_failing, _ = EvaluationLoop(strategy).split([result])
        strategy.write_verdicts(graduated + still_failing)
        assert "expect" in result.content


class TestExhaustionActuallyHalts:
    def test_the_exhaustion_error_is_not_swallowed_by_the_batch_handler(self):
        """The batch loop re-raises RuntimeError and logs-and-continues anything else.

        `on_exhausted: raise` is documented as halting the run, so the error it
        raises has to be one the batch loop does not swallow.
        """
        assert issubclass(ExpectationsExhaustedError, RuntimeError)

    def test_it_still_carries_what_failed(self):
        error = ExpectationsExhaustedError("author", ["positive"], 2)
        assert error.action_name == "author"
        assert error.failed_ids == ["positive"]
        assert error.iterations == 2

    def test_it_is_still_catchable_as_itself(self):
        with pytest.raises(ExpectationsExhaustedError):
            raise ExpectationsExhaustedError("author", [], 1)


class TestRepairDoesNotDiscardTheRestOfRecoveryState:
    """A repair round writes state; the retry and reprompt bookkeeping in it must survive.

    `exhausted_recovery` is rebuilt from `missing_ids`/`record_failure_counts`
    at finalisation, so dropping them loses every record's retry-exhaustion
    metadata whenever a repair round happens to fire.
    """

    def test_the_retry_bookkeeping_survives_a_repair_round(self):
        from agent_actions.llm.batch.services.repair_ops import carry_forward

        prior = RecoveryState(
            missing_ids=["m1"],
            record_failure_counts={"m1": 2},
            retry_attempt=1,
            reprompt_attempt=2,
            reprompt_attempts_per_record={"r1": 1},
            validation_name="schema",
            failure_type_counts={"r1": {"udf_fail": 1}},
        )
        state = carry_forward(prior, repair_attempt=1, repair_max_attempts=2, graduated=[])
        assert state.missing_ids == ["m1"]
        assert state.record_failure_counts == {"m1": 2}
        assert state.retry_attempt == 1
        assert state.reprompt_attempt == 2
        assert state.reprompt_attempts_per_record == {"r1": 1}
        assert state.validation_name == "schema"
        assert state.failure_type_counts == {"r1": {"udf_fail": 1}}

    def test_the_repair_counters_are_set(self):
        from agent_actions.llm.batch.services.repair_ops import carry_forward

        state = carry_forward(None, repair_attempt=1, repair_max_attempts=2, graduated=[])
        assert state.repair_attempt == 1
        assert state.repair_max_attempts == 2

    def test_it_works_with_no_prior_state(self):
        from agent_actions.llm.batch.services.repair_ops import carry_forward

        state = carry_forward(None, repair_attempt=1, repair_max_attempts=1, graduated=[])
        assert state.missing_ids == []
        assert state.graduated_results == []


class TestRecordsTheProviderDropsAreNotLost:
    """A record submitted for repair and never returned must still reach the output.

    The reprompt path stamps and graduates dropped records. Repair submits in one
    pass and collects in another, so the ids it sent have to be persisted for the
    resuming pass to notice what came back.
    """

    def test_submitted_ids_are_persisted_for_the_resuming_pass(self):
        from agent_actions.llm.batch.services.repair_ops import carry_forward

        state = carry_forward(
            None, repair_attempt=1, repair_max_attempts=2, graduated=[], submitted_ids=["r1", "r2"]
        )
        assert sorted(state.repair_submitted_ids) == ["r1", "r2"]

    def test_a_dropped_record_is_identified_against_what_came_back(self):
        from agent_actions.llm.batch.services.repair_ops import dropped_from

        returned = [BatchResult(custom_id="r1", content={"score": 1}, success=True)]
        assert dropped_from(["r1", "r2"], returned) == {"r2"}

    def test_nothing_dropped_is_an_empty_set(self):
        from agent_actions.llm.batch.services.repair_ops import dropped_from

        returned = [BatchResult(custom_id="r1", content={"score": 1}, success=True)]
        assert dropped_from(["r1"], returned) == set()


class TestTheGraduatedPoolIsASet:
    """A record graduates once, however many times its batch is re-processed.

    The original batch stays COMPLETED at the provider, so every resume
    re-processes it and re-graduates the same records. Appending them to the
    persisted pool ships each one again for the same source.
    """

    def test_re_graduating_a_record_does_not_duplicate_it(self):
        from agent_actions.llm.batch.services.repair_ops import carry_forward

        ok = BatchResult(custom_id="ok", content={"score": 5}, success=True)
        first = carry_forward(None, repair_attempt=1, repair_max_attempts=2, graduated=[ok])
        second = carry_forward(first, repair_attempt=1, repair_max_attempts=2, graduated=[ok])
        assert [r["custom_id"] for r in second.graduated_results] == ["ok"]

    def test_a_later_verdict_for_the_same_record_replaces_the_earlier_one(self):
        from agent_actions.llm.batch.services.repair_ops import carry_forward

        first_try = BatchResult(custom_id="r1", content={"score": -1}, success=True)
        repaired = BatchResult(custom_id="r1", content={"score": 9}, success=True)
        first = carry_forward(None, repair_attempt=1, repair_max_attempts=2, graduated=[first_try])
        second = carry_forward(first, repair_attempt=2, repair_max_attempts=2, graduated=[repaired])
        assert len(second.graduated_results) == 1
        assert second.graduated_results[0]["content"]["score"] == 9

    def test_distinct_records_still_accumulate(self):
        from agent_actions.llm.batch.services.repair_ops import carry_forward

        a = BatchResult(custom_id="a", content={"score": 1}, success=True)
        b = BatchResult(custom_id="b", content={"score": 2}, success=True)
        first = carry_forward(None, repair_attempt=1, repair_max_attempts=2, graduated=[a])
        second = carry_forward(first, repair_attempt=2, repair_max_attempts=2, graduated=[b])
        assert sorted(r["custom_id"] for r in second.graduated_results) == ["a", "b"]


class TestProviderErrorsSurviveSerialisation:
    def test_the_error_message_is_not_lost(self):
        """A carried provider failure whose error is dropped reports a generic
        'Batch processing failed' downstream instead of what actually happened."""
        from agent_actions.llm.batch.services.retry_serialization import (
            deserialize_results,
            serialize_results,
        )

        failed = BatchResult(custom_id="e1", content=None, success=False, error="429 rate limited")
        restored = deserialize_results(serialize_results([failed]))
        assert restored[0].error == "429 rate limited"
