"""Batch runs the repair loop, so the same expect: block works in either run_mode.

Online, `ExpectationService.execute` loops around one call. Batch cannot loop per
record — it loops the whole set, resubmitting only what failed. These tests drive
that loop against a provider that records what it was actually sent.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.expectations.service import ExpectationsExhaustedError
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.services import repair_ops, resubmission
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
        "min": 2,
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


def _run(results, second_round, agent_config, provider=None):
    """Drive the repair loop; `second_round` is what the resubmission returns."""
    provider = provider or RecordingProvider()
    provider.retrieve_results = lambda batch_id, output_directory: second_round

    prepared = MagicMock()
    prepared.formatted_prompt = ORIGINAL_PROMPT
    prepared.llm_context = {"source": {"text": "the original input"}}
    prepared.should_execute = True

    with (
        patch("agent_actions.processing.task_preparer.TaskPreparer.prepare", return_value=prepared),
        patch.object(resubmission, "wait_for_batch_completion", return_value=BatchStatus.COMPLETED),
    ):
        out = repair_ops.repair_expectations(
            action_indices={ACTION: 0},
            dependency_configs={},
            storage_backend=None,
            results=results,
            provider=provider,
            context_map=_context_map(),
            output_directory="/tmp/test",
            file_name="f.json",
            agent_config=agent_config,
        )
    return out, provider


def _system_message(provider: RecordingProvider) -> str:
    assert provider.submitted, "nothing was submitted"
    return provider.submitted[0]["body"]["messages"][0]["content"]


class TestTheLoopResubmitsWhatFailed:
    def test_a_failing_record_is_sent_back_to_the_model(self):
        failing = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        repaired = BatchResult(custom_id=CUSTOM_ID, content=PASSING, success=True)
        _out, provider = _run([failing], [repaired], _agent_config(repair="auto"))
        assert provider.submitted, "a record that failed its expectations was never resubmitted"

    def test_a_passing_record_is_never_resubmitted(self):
        passing = BatchResult(custom_id=CUSTOM_ID, content=PASSING, success=True)
        _out, provider = _run([passing], [], _agent_config(repair="auto"))
        assert provider.submitted == []

    def test_observe_mode_does_not_resubmit(self):
        failing = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        out, provider = _run([failing], [], _agent_config(repair="none"))
        assert provider.submitted == []
        assert out[0].content == FAILING

    def test_the_repaired_content_replaces_the_first_attempt(self):
        failing = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        repaired = BatchResult(custom_id=CUSTOM_ID, content=PASSING, success=True)
        out, _provider = _run([failing], [repaired], _agent_config(repair="auto"))
        assert out[0].content["options"] == ["a", "b"]


class TestTheModelIsToldWhatFailed:
    def test_auto_appends_the_failed_rule_and_its_hint(self):
        failing = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        repaired = BatchResult(custom_id=CUSTOM_ID, content=PASSING, success=True)
        _out, provider = _run([failing], [repaired], _agent_config(repair="auto"))
        sent = _system_message(provider)
        assert "enough_options" in sent
        assert "list at least two options" in sent

    def test_the_feedback_follows_the_original_prompt(self):
        failing = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        repaired = BatchResult(custom_id=CUSTOM_ID, content=PASSING, success=True)
        _out, provider = _run([failing], [repaired], _agent_config(repair="auto"))
        sent = _system_message(provider)
        assert sent.index(ORIGINAL_PROMPT) < sent.index("enough_options")

    def test_retry_resends_the_prompt_unchanged(self):
        failing = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        repaired = BatchResult(custom_id=CUSTOM_ID, content=PASSING, success=True)
        _out, provider = _run([failing], [repaired], _agent_config(repair="retry"))
        assert "enough_options" not in _system_message(provider)


class TestTheVerdictLandsOnTheRecord:
    def test_a_repaired_record_carries_a_passing_verdict(self):
        failing = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        repaired = BatchResult(custom_id=CUSTOM_ID, content=PASSING, success=True)
        out, _provider = _run([failing], [repaired], _agent_config(repair="auto"))
        assert out[0].content["expect"]["overall_pass"] is True

    def test_a_record_that_never_failed_still_carries_its_verdict(self):
        passing = BatchResult(custom_id=CUSTOM_ID, content=PASSING, success=True)
        out, _provider = _run([passing], [], _agent_config(repair="auto"))
        assert out[0].content["expect"]["overall_pass"] is True

    def test_an_exhausted_record_carries_the_failing_verdict_it_ended_on(self):
        failing = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        still = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        out, _provider = _run([failing], [still], _agent_config(repair="auto", max_iterations=2))
        assert out[0].content["expect"]["overall_pass"] is False
        assert out[0].content["expect"]["failed"] == ["enough_options"]


class TestExhaustion:
    def _exhaust(self, **expect):
        failing = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        still = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        return _run([failing], [still], _agent_config(repair="auto", max_iterations=2, **expect))

    def test_return_last_keeps_the_record(self):
        out, _provider = self._exhaust(on_exhausted="return_last")
        assert out[0].success is True
        assert out[0].content["options"] == ["only-one"]

    def test_exhaustion_records_the_iterations_and_what_failed(self):
        out, _provider = self._exhaust(on_exhausted="return_last")
        expectations = out[0].recovery_metadata.expectations
        assert expectations.attempts == 2
        assert expectations.failed == ["enough_options"]

    def test_fail_turns_the_record_into_a_failure(self):
        out, _provider = self._exhaust(on_exhausted="fail")
        assert out[0].success is False
        assert "Expectations exhausted" in out[0].error
        assert "enough_options" in out[0].error

    def test_raise_halts_the_run(self):
        with pytest.raises(ExpectationsExhaustedError):
            self._exhaust(on_exhausted="raise")

    def test_max_iterations_bounds_the_number_of_generations(self):
        failing = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        still = BatchResult(custom_id=CUSTOM_ID, content=FAILING, success=True)
        provider = RecordingProvider()
        provider.submissions = 0
        original = provider.submit_batch

        def counting(tasks, batch_name, output_directory):
            provider.submissions += 1
            return original(tasks, batch_name, output_directory)

        provider.submit_batch = counting
        _run(
            [failing],
            [still],
            _agent_config(repair="auto", max_iterations=3),
            provider=provider,
        )
        # 3 total generations = the first, already in hand, plus two resubmissions.
        assert provider.submissions == 2


class TestInnerRecoveryIsNotLost:
    def test_a_repaired_record_keeps_its_reprompt_history(self):
        from agent_actions.processing.types import RecoveryMetadata, RepromptMetadata

        failing = BatchResult(
            custom_id=CUSTOM_ID,
            content=FAILING,
            success=True,
            recovery_metadata=RecoveryMetadata(
                reprompt=RepromptMetadata(attempts=2, passed=True, validation="schema")
            ),
        )
        repaired = BatchResult(custom_id=CUSTOM_ID, content=PASSING, success=True)
        out, _provider = _run([failing], [repaired], _agent_config(repair="auto"))
        assert out[0].recovery_metadata.reprompt.attempts == 2
