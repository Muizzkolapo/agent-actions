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
    expectations=[{"id": "positive", "type": "expression", "params": {"condition": "score > 0"}}],
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


class TestPoolingIsOneAuthority:
    """Both the submit path and the resume path add to the graduated pool.

    Two call sites means two chances to forget the dedupe, and the pool is what
    finalisation ships — a record in it twice is a duplicate output row.
    """

    def test_pooling_the_same_record_twice_keeps_one(self):
        from agent_actions.llm.batch.services.repair_ops import pool_records

        err = BatchResult(custom_id="e1", content=None, success=False, error="429")
        pooled = pool_records([], [err])
        pooled = pool_records(pooled, [err])
        assert [r["custom_id"] for r in pooled] == ["e1"]

    def test_the_later_record_wins(self):
        from agent_actions.llm.batch.services.repair_ops import pool_records

        first = BatchResult(custom_id="r1", content={"score": -1}, success=True)
        later = BatchResult(custom_id="r1", content={"score": 9}, success=True)
        pooled = pool_records(pool_records([], [first]), [later])
        assert pooled[0]["content"]["score"] == 9

    def test_distinct_records_accumulate(self):
        from agent_actions.llm.batch.services.repair_ops import pool_records

        a = BatchResult(custom_id="a", content={"score": 1}, success=True)
        b = BatchResult(custom_id="b", content={"score": 2}, success=True)
        pooled = pool_records(pool_records([], [a]), [b])
        assert sorted(r["custom_id"] for r in pooled) == ["a", "b"]

    def test_the_error_survives_pooling(self):
        from agent_actions.llm.batch.services.repair_ops import pool_records

        err = BatchResult(custom_id="e1", content=None, success=False, error="429 rate limited")
        assert pool_records([], [err])[0]["error"] == "429 rate limited"


class TestTheDedupeKeyCannotCollapseDistinctRecords:
    def test_two_records_without_an_id_are_not_merged(self):
        from agent_actions.llm.batch.services.repair_ops import pool_records

        a = BatchResult(custom_id="", content={"score": 1}, success=True)
        b = BatchResult(custom_id="", content={"score": 2}, success=True)
        pooled = pool_records([], [a, b])
        assert len(pooled) == 2, "records with no id collapsed into one"


class TestTheUnidentifiedSentinelIsNotAnIdentity:
    """A provider stamps a result carrying no correlation id with a sentinel.

    Two such results are two records. Deduplicating on the sentinel folds them
    into one and loses a record silently, which is worse than shipping both.
    """

    def test_two_unidentified_results_are_two_records(self):
        from agent_actions.llm.batch.services.repair_ops import pool_records
        from agent_actions.llm.providers.batch_base import UNIDENTIFIED_RECORD

        a = BatchResult(custom_id=UNIDENTIFIED_RECORD, content={"score": 1}, success=True)
        b = BatchResult(custom_id=UNIDENTIFIED_RECORD, content={"score": 2}, success=True)
        assert len(pool_records([], [a, b])) == 2

    def test_they_stay_separate_across_rounds(self):
        from agent_actions.llm.batch.services.repair_ops import pool_records
        from agent_actions.llm.providers.batch_base import UNIDENTIFIED_RECORD

        a = BatchResult(custom_id=UNIDENTIFIED_RECORD, content={"score": 1}, success=True)
        b = BatchResult(custom_id=UNIDENTIFIED_RECORD, content={"score": 2}, success=True)
        assert len(pool_records(pool_records([], [a]), [b])) == 2

    def test_an_identified_record_still_deduplicates(self):
        from agent_actions.llm.batch.services.repair_ops import pool_records

        ok = BatchResult(custom_id="r1", content={"score": 1}, success=True)
        assert len(pool_records([], [ok, ok])) == 1


class TestTheSentinelMatchesWhatProvidersEmit:
    """`pool_records` compares against a constant the providers produce.

    Two copies of a value one side writes and the other compares is how the
    dedupe silently stops working — pin both ends to the same source.
    """

    def test_the_base_extractor_defaults_to_the_sentinel(self):
        from agent_actions.llm.providers.batch_base import UNIDENTIFIED_RECORD

        from .test_reprompt_feedback_delivery import RecordingProvider

        assert RecordingProvider()._extract_custom_id({}) == UNIDENTIFIED_RECORD

    def test_the_gemini_override_defaults_to_the_same_sentinel(self):
        pytest.importorskip("google.genai")
        from agent_actions.llm.providers.batch_base import UNIDENTIFIED_RECORD
        from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient

        assert GeminiBatchClient.__dict__["_extract_custom_id"](object(), {}) == UNIDENTIFIED_RECORD


class TestTheSentinelDoesNotCollideWithUserData:
    """A record whose id is literally the sentinel is still a real record.

    The pool treats the sentinel as "no usable id" and lets those through
    undeduplicated, which is right for a record that genuinely lost its
    correlation. It is wrong for a user record that happens to be named that:
    the original batch is re-processed on every pass, so it accumulates one copy
    per pass, unbounded.
    """

    def test_a_record_named_like_the_old_sentinel_deduplicates(self):
        from agent_actions.llm.batch.services.repair_ops import pool_records

        pooled: list = []
        for _ in range(3):
            rec = BatchResult(custom_id="unknown", content={"score": 1}, success=True)
            pooled = pool_records(pooled, [rec])
        ids = [r.get("custom_id") for r in pooled]
        assert ids == ["unknown"], (
            f"a user record named 'unknown' grew one copy per pass ({ids}); the sentinel must not "
            "share a namespace with real ids"
        )

    def test_a_genuinely_unidentified_record_is_still_not_deduplicated(self):
        from agent_actions.llm.batch.services.repair_ops import pool_records
        from agent_actions.llm.providers.batch_base import UNIDENTIFIED_RECORD

        a = BatchResult(custom_id=UNIDENTIFIED_RECORD, content={"score": 1}, success=True)
        b = BatchResult(custom_id=UNIDENTIFIED_RECORD, content={"score": 2}, success=True)
        pooled = pool_records([], [a, b])
        assert len(pooled) == 2, (
            "two records that both lost their correlation are not known to be the same record; "
            "folding them together drops one"
        )

    def test_evicting_an_in_flight_id_does_not_take_unidentified_records_with_it(self):
        """Eviction needs an identity too, or one resubmission drops the rest.

        A record with no correlation id cannot be matched to a submission, so it
        was never sent — evicting it because some *other* unidentified record
        was is a silent loss, and losing them is worse than duplicating them.
        """
        from agent_actions.llm.batch.services.repair_ops import pool_records
        from agent_actions.llm.providers.batch_base import UNIDENTIFIED_RECORD

        pooled = pool_records(
            [],
            [
                BatchResult(custom_id="r1", content={"score": 1}, success=True),
                BatchResult(custom_id=UNIDENTIFIED_RECORD, content={"score": 2}, success=True),
                BatchResult(
                    custom_id=UNIDENTIFIED_RECORD, content=None, success=False, error="429"
                ),
            ],
        )
        kept = pool_records(pooled, [], in_flight=[UNIDENTIFIED_RECORD])
        errors = [r.get("error") for r in kept]
        assert len(kept) == 3, f"an unidentified record was evicted and lost: {kept}"
        assert "429" in errors, "the provider's real error was destroyed"

    def test_an_identified_record_in_flight_is_still_evicted(self):
        from agent_actions.llm.batch.services.repair_ops import pool_records

        pooled = pool_records([], [BatchResult(custom_id="r1", content={"s": 1}, success=True)])
        assert pool_records(pooled, [], in_flight=["r1"]) == []
