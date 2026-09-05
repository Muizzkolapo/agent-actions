"""Batch runs the repair loop, so the same expect: block works in either run_mode.

Online, `ExpectationService.execute` loops around one call. Batch cannot: a round
is a whole batch submission, so it defers like a reprompt round and resumes on the
next pass. These tests cover the pieces that carry the loop's decisions — what the
model is sent, and what happens when the iterations run out.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.expectations.service import ExpectationsExhaustedError
from agent_actions.llm.batch.services.repair_ops import (
    apply_exhaustion_policy,
    build_repair_strategy,
    stamp_exhausted,
    submit_repair_batch,
)
from agent_actions.llm.providers.batch_base import BatchResult

from .test_reprompt_feedback_delivery import RecordingProvider

ACTION = "author"
CUSTOM_ID = "t-001"
ORIGINAL_PROMPT = "Write the options."

EXPECTATIONS = [
    {
        "id": "enough_options",
        "type": "item_count",
        "field": "options",
        "params": {"min": 2},
        "hint": "list at least two options",
    }
]

FAILING = {"options": ["only-one"]}
PASSING = {"options": ["a", "b"]}


def _agent_config(**expect: Any) -> dict[str, Any]:
    return {
        "name": ACTION,
        "action_name": ACTION,
        "agent_type": ACTION,
        "json_mode": False,
        "model_name": "test-model",
        "prompt": ORIGINAL_PROMPT,
        "run_mode": "batch",
        "expect": {"expectations": EXPECTATIONS, **expect},
    }


def _context_map() -> dict[str, Any]:
    return {
        CUSTOM_ID: {
            "target_id": CUSTOM_ID,
            "source_guid": "sg-1",
            "content": {"source": {"text": "the original input"}},
        }
    }


def _submit(repair: str = "auto", content: Any = FAILING) -> RecordingProvider:
    """Run one repair submission and hand back what the provider received."""
    strategy = build_repair_strategy(_agent_config(repair=repair))
    failed = BatchResult(custom_id=CUSTOM_ID, content=content, success=True)
    strategy.evaluate(failed)

    provider = RecordingProvider()
    prepared = MagicMock()
    prepared.formatted_prompt = ORIGINAL_PROMPT
    prepared.llm_context = {"source": {"text": "the original input"}}
    prepared.should_execute = True

    with patch(
        "agent_actions.processing.task_preparer.TaskPreparer.prepare", return_value=prepared
    ):
        submit_repair_batch(
            action_indices={ACTION: 0},
            dependency_configs={},
            storage_backend=None,
            provider=provider,
            failed_results=[failed],
            strategy=strategy,
            context_map=_context_map(),
            output_directory="/tmp/test",
            file_name="f.json",
            agent_config=_agent_config(repair=repair),
            attempt=1,
        )
    return provider


def _system_message(provider: RecordingProvider) -> str:
    assert provider.submitted, "nothing was submitted"
    return provider.submitted[0]["body"]["messages"][0]["content"]


class TestWhetherTheActionRepairsAtAll:
    def test_a_repair_policy_builds_a_strategy(self):
        assert build_repair_strategy(_agent_config(repair="auto")) is not None

    def test_observe_mode_does_not(self):
        assert build_repair_strategy(_agent_config(repair="none")) is None

    def test_an_action_with_no_expect_block_does_not(self):
        assert build_repair_strategy({"name": ACTION, "action_name": ACTION}) is None


class TestTheModelIsToldWhatFailed:
    def test_auto_appends_the_failed_rule_and_its_hint(self):
        sent = _system_message(_submit("auto"))
        assert "enough_options" in sent
        assert "list at least two options" in sent

    def test_auto_carries_the_previous_output_back(self):
        assert "only-one" in _system_message(_submit("auto"))

    def test_the_feedback_follows_the_original_prompt(self):
        sent = _system_message(_submit("auto"))
        assert sent.index(ORIGINAL_PROMPT) < sent.index("enough_options"), (
            "the original instruction must come first, with the failure list after it"
        )

    def test_retry_resends_the_prompt_unchanged(self):
        assert "enough_options" not in _system_message(_submit("retry"))

    def test_a_record_missing_from_the_context_map_is_not_submitted(self):
        strategy = build_repair_strategy(_agent_config(repair="auto"))
        failed = BatchResult(custom_id="unknown", content=FAILING, success=True)
        provider = RecordingProvider()
        submitted = submit_repair_batch(
            action_indices={ACTION: 0},
            dependency_configs={},
            storage_backend=None,
            provider=provider,
            failed_results=[failed],
            strategy=strategy,
            context_map=_context_map(),
            output_directory="/tmp/test",
            file_name="f.json",
            agent_config=_agent_config(repair="auto"),
            attempt=1,
        )
        assert submitted is None
        assert provider.submitted == []


class TestTheVerdictLandsOnTheRecord:
    def test_write_verdicts_annotates_the_record_it_judged(self):
        strategy = build_repair_strategy(_agent_config(repair="auto"))
        result = BatchResult(custom_id=CUSTOM_ID, content=PASSING, success=True)
        strategy.evaluate(result)
        strategy.write_verdicts([result])
        assert result.content["expect"]["overall_pass"] is True

    def test_a_failing_record_carries_the_rule_that_failed(self):
        strategy = build_repair_strategy(_agent_config(repair="auto"))
        result = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        strategy.evaluate(result)
        strategy.write_verdicts([result])
        assert result.content["expect"]["overall_pass"] is False
        assert result.content["expect"]["failed"] == ["enough_options"]

    def test_every_record_of_an_expansion_gets_its_own_verdict(self):
        strategy = build_repair_strategy(_agent_config(repair="auto"))
        result = BatchResult(custom_id=CUSTOM_ID, content=[PASSING, FAILING], success=True)
        strategy.evaluate(result)
        strategy.write_verdicts([result])
        assert result.content[0]["expect"]["overall_pass"] is True
        assert result.content[1]["expect"]["overall_pass"] is False


class TestExhaustion:
    def _exhausted(self, **expect) -> tuple[list[BatchResult], Any]:
        strategy = build_repair_strategy(_agent_config(repair="auto", **expect))
        result = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        strategy.evaluate(result)
        stamp_exhausted([result], strategy, attempts=2)
        return [result], strategy

    def test_exhaustion_records_the_iterations_and_what_failed(self):
        results, _strategy = self._exhausted()
        expectations = results[0].recovery_metadata.expectations
        assert expectations.attempts == 2
        assert expectations.failed == ["enough_options"]

    def test_return_last_keeps_the_record(self):
        results, strategy = self._exhausted(on_exhausted="return_last")
        apply_exhaustion_policy(results, strategy, ACTION)
        assert results[0].success is True
        assert results[0].content["options"] == ["only-one"]

    def test_fail_turns_the_record_into_a_failure(self):
        results, strategy = self._exhausted(on_exhausted="fail")
        apply_exhaustion_policy(results, strategy, ACTION)
        assert results[0].success is False
        assert "Expectations exhausted" in results[0].error
        assert "enough_options" in results[0].error

    def test_raise_hands_back_the_error_rather_than_throwing_it(self):
        """The caller has not written the output file yet.

        Throwing here would halt by discarding every record the round had
        already graduated, so the error travels back and is raised once the
        file is on disk.
        """
        results, strategy = self._exhausted(on_exhausted="raise")
        pending = apply_exhaustion_policy(results, strategy, ACTION)
        assert isinstance(pending, ExpectationsExhaustedError)
        assert pending.failed_ids == ["enough_options"]

    def test_the_other_policies_hand_back_nothing_to_raise(self):
        for policy in ("return_last", "fail"):
            results, strategy = self._exhausted(on_exhausted=policy)
            assert apply_exhaustion_policy(results, strategy, ACTION) is None, policy

    def test_nothing_exhausted_is_not_a_failure(self):
        _results, strategy = self._exhausted(on_exhausted="raise")
        apply_exhaustion_policy([], strategy, ACTION)


class TestOnlyWhatWasSentCountsAsInFlight:
    """A record the submission skipped was never sent, so it never went missing.

    `submit_repair_batch` skips a record with no `context_map` row — it has
    nothing to rebuild the prompt from. Recording it as submitted anyway makes
    the next round reconstruct it as a provider drop, destroying content that
    was already generated and paid for and replacing it with a claim that is
    false.
    """

    def _submit(self, failed_ids: list[str]):
        strategy = build_repair_strategy(_agent_config(repair="auto"))
        failed = [
            BatchResult(custom_id=cid, content=dict(FAILING), success=True) for cid in failed_ids
        ]
        for f in failed:
            strategy.evaluate(f)
        provider = RecordingProvider()
        prepared = MagicMock()
        prepared.formatted_prompt = ORIGINAL_PROMPT
        prepared.llm_context = {"source": {"text": "the original input"}}
        prepared.should_execute = True
        with patch(
            "agent_actions.processing.task_preparer.TaskPreparer.prepare", return_value=prepared
        ):
            return submit_repair_batch(
                action_indices={ACTION: 0},
                dependency_configs={},
                storage_backend=None,
                provider=provider,
                failed_results=failed,
                strategy=strategy,
                context_map=_context_map(),
                output_directory="/tmp/test",
                file_name="f.json",
                agent_config=_agent_config(repair="auto"),
                attempt=1,
            )

    def test_a_skipped_record_is_not_reported_as_sent(self):
        submission = self._submit([CUSTOM_ID, "no-context-row"])
        assert submission is not None
        assert submission.sent_ids == [CUSTOM_ID], (
            f"{submission.sent_ids} claims a record was submitted that the preparator skipped; "
            "next round reconstructs it as a provider drop over its real content"
        )

    def test_the_batch_id_and_count_still_come_back(self):
        submission = self._submit([CUSTOM_ID])
        assert submission.batch_id
        assert submission.record_count == 1
        assert submission.sent_ids == [CUSTOM_ID]


class TestFailKeepsTheRealCause:
    """A record that failed at the provider did not fail its expectations.

    `still_failing` carries both: records the suite rejected, and records that
    never produced content at all. Overwriting the second kind's error replaces
    a true, actionable cause with a claim that is false — and the message even
    reports `failed: none`, because there was no verdict to report.
    """

    def _apply(self, *results: BatchResult):
        strategy = build_repair_strategy(_agent_config(repair="auto", on_exhausted="fail"))
        for r in results:
            if r.content is not None:
                strategy.evaluate(r)
        stamp_exhausted(list(results), strategy, attempts=2)
        apply_exhaustion_policy(list(results), strategy, ACTION)
        return results

    def test_a_provider_failure_keeps_its_own_error(self):
        provider_failure = BatchResult(
            custom_id="gone", content=None, success=False, error="429 rate limited"
        )
        rejected = BatchResult(custom_id=CUSTOM_ID, content=dict(FAILING), success=True)
        self._apply(provider_failure, rejected)
        assert "429 rate limited" in (provider_failure.error or ""), (
            f"the provider's cause was replaced by {provider_failure.error!r}; the operator is "
            "told the expectations failed when the model was never reached"
        )

    def test_a_rejected_record_still_reports_its_expectations(self):
        rejected = BatchResult(custom_id=CUSTOM_ID, content=dict(FAILING), success=True)
        self._apply(rejected)
        assert rejected.success is False
        assert "Expectations exhausted" in (rejected.error or "")
        assert "enough_options" in (rejected.error or "")


class TestAnExhaustedRecordKeepsTheRuleThatFailed:
    """A record the round never re-evaluated still failed something.

    The verdict map is rebuilt each round, so a record sent for repair that the
    provider never returned has no verdict this pass. Stamping it with an empty
    `failed` list says nothing failed — and the halt message then reads
    "still failing: (none)" exactly when a human is being interrupted.
    """

    def test_a_record_with_no_fresh_verdict_keeps_its_recorded_one(self):
        strategy = build_repair_strategy(_agent_config(repair="auto"))
        sent = BatchResult(custom_id=CUSTOM_ID, content=dict(FAILING), success=True)
        strategy.evaluate(sent)
        stamp_exhausted([sent], strategy, attempts=1)

        # Next round: the provider never returned it, so it is reconstructed
        # with no content and a fresh strategy has never seen it.
        fresh = build_repair_strategy(_agent_config(repair="auto"))
        dropped = BatchResult(
            custom_id=CUSTOM_ID, content=None, success=False, error="never returned"
        )
        dropped.recovery_metadata = sent.recovery_metadata
        stamp_exhausted([dropped], fresh, attempts=2)

        expectations = dropped.recovery_metadata.expectations
        assert expectations.attempts == 2
        assert expectations.failed == ["enough_options"], (
            f"the rule it failed was lost ({expectations.failed}); the output and the halt message "
            "both then claim nothing failed"
        )

    def test_a_fresh_verdict_still_wins(self):
        strategy = build_repair_strategy(_agent_config(repair="auto"))
        result = BatchResult(custom_id=CUSTOM_ID, content=dict(FAILING), success=True)
        result.recovery_metadata = None
        strategy.evaluate(result)
        stamp_exhausted([result], strategy, attempts=3)
        assert result.recovery_metadata.expectations.failed == ["enough_options"]

    def test_a_record_that_never_failed_anything_records_nothing(self):
        strategy = build_repair_strategy(_agent_config(repair="auto"))
        result = BatchResult(custom_id=CUSTOM_ID, content=dict(PASSING), success=True)
        strategy.evaluate(result)
        stamp_exhausted([result], strategy, attempts=1)
        assert result.recovery_metadata.expectations.failed == []


def test_a_repair_round_stamps_its_round_number_on_the_prompt_trace():
    strategy = build_repair_strategy(_agent_config(repair="auto"))
    failed = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
    strategy.evaluate(failed)

    prepared = MagicMock()
    prepared.formatted_prompt = ORIGINAL_PROMPT
    prepared.llm_context = {"source": {"text": "the original input"}}
    prepared.should_execute = True

    with patch(
        "agent_actions.processing.task_preparer.TaskPreparer.prepare", return_value=prepared
    ) as prepare:
        submit_repair_batch(
            action_indices={ACTION: 0},
            dependency_configs={},
            storage_backend=None,
            provider=RecordingProvider(),
            failed_results=[failed],
            strategy=strategy,
            context_map=_context_map(),
            output_directory="/tmp/test",
            file_name="f.json",
            agent_config=_agent_config(repair="auto"),
            attempt=2,
        )

    # A trace row is keyed (action, record, attempt) and written INSERT OR REPLACE,
    # so a round that does not stamp its number overwrites the previous prompt.
    assert prepare.call_args.kwargs["attempt"] == 2
