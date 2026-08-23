"""Judge LLM invocation: prompt construction and verdict parsing."""

import json
from unittest.mock import patch

import pytest

from agent_actions.expectations import registry
from agent_actions.expectations.judge import build_judge_prompt, invoke_judge

INVOKE = "agent_actions.llm.realtime.services.invocation.ClientInvocationService.invoke_client"


def _agent_config(**overrides):
    return {
        "model_vendor": "anthropic",
        "model_name": "claude-sonnet-5",
        "name": "write_q",
        **overrides,
    }


def _client_result(passed: bool, reason: str = "looks fine"):
    return [{"content": json.dumps({"passed": passed, "reason": reason})}]


class TestBuildJudgePrompt:
    def test_includes_rule_and_value(self):
        prompt = build_judge_prompt("Options must be specific.", "a vague option", context=None)
        assert "Options must be specific." in prompt
        assert "a vague option" in prompt

    def test_omits_context_section_when_none(self):
        prompt = build_judge_prompt("rule", "value", context=None)
        assert "Grounding context" not in prompt

    def test_includes_context_section_when_given(self):
        prompt = build_judge_prompt("rule", "value", context={"source_context": "the docs say X"})
        assert "Grounding context" in prompt
        assert "the docs say X" in prompt

    def test_serializes_non_string_value_as_json(self):
        prompt = build_judge_prompt("rule", ["opt a", "opt b"], context=None)
        assert '"opt a"' in prompt


class TestInvokeJudge:
    def test_raises_when_model_vendor_missing(self):
        with pytest.raises(ValueError, match="model_vendor"):
            invoke_judge({"name": "write_q"}, "rule", "value")

    def test_returns_true_and_reason_on_pass(self):
        with patch(INVOKE, return_value=_client_result(True, "meets the rule")) as mock_invoke:
            passed, detail = invoke_judge(_agent_config(), "rule text", "value under test")
        assert passed is True
        assert detail == "meets the rule"
        mock_invoke.assert_called_once()

    def test_returns_false_and_reason_on_fail(self):
        with patch(INVOKE, return_value=_client_result(False, "too vague")):
            passed, detail = invoke_judge(_agent_config(), "rule text", "value under test")
        assert passed is False
        assert detail == "too vague"

    def test_uses_parent_model_vendor_by_default(self):
        with patch(INVOKE, return_value=_client_result(True)) as mock_invoke:
            invoke_judge(_agent_config(), "rule", "value")
        assert mock_invoke.call_args.kwargs["model_vendor"] == "anthropic"
        assert mock_invoke.call_args.kwargs["agent_config"]["model_name"] == "claude-sonnet-5"

    def test_model_override_changes_only_model_name(self):
        with patch(INVOKE, return_value=_client_result(True)) as mock_invoke:
            invoke_judge(_agent_config(), "rule", "value", model="claude-opus-5")
        called_config = mock_invoke.call_args.kwargs["agent_config"]
        assert called_config["model_name"] == "claude-opus-5"
        assert mock_invoke.call_args.kwargs["model_vendor"] == "anthropic"

    def test_schema_is_never_passed_to_invoke_client(self):
        with patch(INVOKE, return_value=_client_result(True)) as mock_invoke:
            invoke_judge(_agent_config(), "rule", "value")
        assert mock_invoke.call_args.kwargs["schema"] is None

    def test_malformed_json_response_is_a_failure(self):
        with patch(INVOKE, return_value=[{"content": "not json at all"}]):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "not a verdict object" in detail

    def test_missing_passed_key_is_a_failure(self):
        with patch(INVOKE, return_value=[{"content": json.dumps({"reason": "no verdict field"})}]):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "boolean 'passed'" in detail

    def test_non_boolean_passed_value_is_a_failure(self):
        with patch(INVOKE, return_value=[{"content": json.dumps({"passed": "yes"})}]):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False

    def test_empty_result_is_a_failure(self):
        with patch(INVOKE, return_value=[]):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "empty" in detail


class TestVerdictParsingMatchesTheRestOfTheCodebase:
    """A verdict is scored on the value under test, not on the judge's reply syntax.

    Every other consumer of LLM text in the framework goes through
    ``parse_llm_json``. Real judge models routinely answer with a Python literal
    (single quotes, ``True``) or a fenced block; scoring those as rule failures
    reports a passing record as failing.
    """

    PYTHON_LITERAL_PASS = "{'passed': True, 'reason': 'Concrete situation with goal and constraint'}"
    PYTHON_LITERAL_FAIL = "{'passed': False, 'reason': 'It is a definition prompt'}"
    FENCED = '```json\n{"passed": true, "reason": "reads as a scenario"}\n```'

    def test_python_literal_pass_is_a_pass(self):
        with patch(INVOKE, return_value=[{"content": self.PYTHON_LITERAL_PASS}]):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is True
        assert detail == "Concrete situation with goal and constraint"

    def test_python_literal_fail_reports_the_judges_reason(self):
        with patch(INVOKE, return_value=[{"content": self.PYTHON_LITERAL_FAIL}]):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert detail == "It is a definition prompt"

    def test_fenced_verdict_is_read(self):
        with patch(INVOKE, return_value=[{"content": self.FENCED}]):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is True
        assert detail == "reads as a scenario"

    def test_unreadable_reply_still_fails_closed(self):
        with patch(INVOKE, return_value=[{"content": "The value is fine, I would pass it."}]):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "The value is fine" in detail


class TestRegistration:
    def test_llm_judge_is_registered(self):
        etype = registry.get("llm_judge")
        assert etype is not None
        assert etype.required == frozenset({"rule"})
        assert "model" in etype.params

    def test_llm_judge_check_is_unreachable(self):
        etype = registry.get("llm_judge")
        with pytest.raises(NotImplementedError):
            etype.check("value", {"rule": "x"})


class TestInvokeJudgeWithVotes:
    def test_votes_one_delegates_directly(self):
        from agent_actions.expectations.judge import invoke_judge_with_votes

        with patch("agent_actions.expectations.judge.invoke_judge") as mock_judge:
            mock_judge.return_value = (True, "fine")
            passed, detail = invoke_judge_with_votes(_agent_config(), "rule", "value", votes=1)
        assert passed is True
        assert detail == "fine"
        mock_judge.assert_called_once()

    def test_votes_defaults_to_one(self):
        from agent_actions.expectations.judge import invoke_judge_with_votes

        with patch("agent_actions.expectations.judge.invoke_judge") as mock_judge:
            mock_judge.return_value = (True, "fine")
            invoke_judge_with_votes(_agent_config(), "rule", "value")
        mock_judge.assert_called_once()

    def test_majority_pass_wins(self):
        from agent_actions.expectations.judge import invoke_judge_with_votes

        with patch("agent_actions.expectations.judge.invoke_judge") as mock_judge:
            mock_judge.side_effect = [(True, "ok"), (True, "ok"), (False, "too vague")]
            passed, detail = invoke_judge_with_votes(_agent_config(), "rule", "value", votes=3)
        assert passed is True
        assert "2/3" in detail

    def test_majority_fail_wins_and_reports_dissenting_reasons(self):
        from agent_actions.expectations.judge import invoke_judge_with_votes

        with patch("agent_actions.expectations.judge.invoke_judge") as mock_judge:
            mock_judge.side_effect = [
                (True, "ok"),
                (False, "too vague"),
                (False, "not falsifiable"),
            ]
            passed, detail = invoke_judge_with_votes(_agent_config(), "rule", "value", votes=3)
        assert passed is False
        assert "too vague" in detail
        assert "not falsifiable" in detail

    def test_exact_tie_fails_closed(self):
        from agent_actions.expectations.judge import invoke_judge_with_votes

        with patch("agent_actions.expectations.judge.invoke_judge") as mock_judge:
            mock_judge.side_effect = [(True, "ok"), (False, "no")]
            passed, _ = invoke_judge_with_votes(_agent_config(), "rule", "value", votes=2)
        assert passed is False

    def test_every_vote_receives_identical_arguments(self):
        from agent_actions.expectations.judge import invoke_judge_with_votes

        with patch("agent_actions.expectations.judge.invoke_judge") as mock_judge:
            mock_judge.return_value = (True, "ok")
            invoke_judge_with_votes(
                _agent_config(),
                "rule text",
                "value",
                votes=3,
                context={"a": "b"},
                model="claude-opus-5",
            )
        assert mock_judge.call_count == 3
        for call in mock_judge.call_args_list:
            assert call.args == (_agent_config(), "rule text", "value")
            assert call.kwargs["context"] == {"a": "b"}
            assert call.kwargs["model"] == "claude-opus-5"


class TestVotesRegistration:
    def test_llm_judge_accepts_votes_param(self):
        etype = registry.get("llm_judge")
        assert "votes" in etype.params


from agent_actions.expectations.types import Expectation


def _judged_expectation(**overrides):
    """Build a judged rule; overrides other than id/field are its params."""
    fields = {"id": "generic_options", "type": "llm_judge", "field": "options"}
    fields.update({k: overrides.pop(k) for k in ("id", "field") if k in overrides})
    return Expectation(params={"rule": "be specific", **overrides}, **fields)


class TestCacheKey:
    def test_same_expectation_and_value_produce_same_key(self):
        from agent_actions.expectations.judge import cache_key

        exp = _judged_expectation()
        assert cache_key(exp, "value a") == cache_key(exp, "value a")

    def test_different_value_produces_different_key(self):
        from agent_actions.expectations.judge import cache_key

        exp = _judged_expectation()
        assert cache_key(exp, "value a") != cache_key(exp, "value b")

    def test_different_id_produces_different_key(self):
        from agent_actions.expectations.judge import cache_key

        a = _judged_expectation(id="rule_one")
        b = _judged_expectation(id="rule_two")
        assert cache_key(a, "value") != cache_key(b, "value")

    def test_editing_the_rule_changes_the_key(self):
        from agent_actions.expectations.judge import cache_key

        original = _judged_expectation(rule="be specific")
        edited = _judged_expectation(rule="be extremely specific")
        assert cache_key(original, "value") != cache_key(edited, "value")

    def test_different_model_produces_different_key(self):
        from agent_actions.expectations.judge import cache_key

        a = _judged_expectation(model="claude-sonnet-5")
        b = _judged_expectation(model="claude-opus-5")
        assert cache_key(a, "value") != cache_key(b, "value")


class TestCachedJudge:
    def test_lookup_is_none_before_any_call(self):
        from agent_actions.expectations.judge import CachedJudge

        judge = CachedJudge(_agent_config())
        assert judge.lookup(_judged_expectation(), "value") is None

    def test_call_and_cache_invokes_the_judge_and_stores_the_result(self):
        from agent_actions.expectations.judge import CachedJudge

        judge = CachedJudge(_agent_config())
        with patch("agent_actions.expectations.judge.invoke_judge_with_votes") as mock_invoke:
            mock_invoke.return_value = (True, "meets the rule")
            passed, detail = judge.call_and_cache(_judged_expectation(), "value")
        assert (passed, detail) == (True, "meets the rule")
        mock_invoke.assert_called_once()

    def test_lookup_returns_the_cached_verdict_after_call_and_cache(self):
        from agent_actions.expectations.judge import CachedJudge

        judge = CachedJudge(_agent_config())
        exp = _judged_expectation()
        with patch(
            "agent_actions.expectations.judge.invoke_judge_with_votes",
            return_value=(False, "too vague"),
        ):
            judge.call_and_cache(exp, "value")
        assert judge.lookup(exp, "value") == (False, "too vague")

    def test_call_and_cache_does_not_consult_its_own_cache(self):
        from agent_actions.expectations.judge import CachedJudge

        judge = CachedJudge(_agent_config())
        exp = _judged_expectation()
        with patch("agent_actions.expectations.judge.invoke_judge_with_votes") as mock_invoke:
            mock_invoke.side_effect = [(True, "first"), (False, "second")]
            judge.call_and_cache(exp, "value")
            judge.call_and_cache(exp, "value")
        assert mock_invoke.call_count == 2
        assert judge.lookup(exp, "value") == (False, "second")

    def test_call_and_cache_passes_rule_votes_model_and_context_through(self):
        from agent_actions.expectations.judge import CachedJudge

        judge = CachedJudge(_agent_config(), action_name="write_q")
        exp = _judged_expectation(votes=3, model="claude-opus-5")
        with patch("agent_actions.expectations.judge.invoke_judge_with_votes") as mock_invoke:
            mock_invoke.return_value = (True, "ok")
            judge.call_and_cache(exp, "value", context={"source_context": "docs say X"})
        mock_invoke.assert_called_once_with(
            _agent_config(),
            "be specific",
            "value",
            votes=3,
            context={"source_context": "docs say X"},
            model="claude-opus-5",
            action_name="write_q",
        )

    def test_distinct_values_cache_independently(self):
        from agent_actions.expectations.judge import CachedJudge

        judge = CachedJudge(_agent_config())
        exp = _judged_expectation()
        with patch("agent_actions.expectations.judge.invoke_judge_with_votes") as mock_invoke:
            mock_invoke.side_effect = [(True, "a passes"), (False, "b fails")]
            judge.call_and_cache(exp, "value a")
            judge.call_and_cache(exp, "value b")
        assert judge.lookup(exp, "value a") == (True, "a passes")
        assert judge.lookup(exp, "value b") == (False, "b fails")


class TestJudgeBudget:
    def test_try_acquire_succeeds_while_calls_remain(self):
        from agent_actions.expectations.judge import JudgeBudget

        budget = JudgeBudget(max_calls=2)
        assert budget.try_acquire() is True
        assert budget.try_acquire() is True

    def test_try_acquire_fails_once_exhausted(self):
        from agent_actions.expectations.judge import JudgeBudget

        budget = JudgeBudget(max_calls=1)
        assert budget.try_acquire() is True
        assert budget.try_acquire() is False

    def test_try_acquire_never_goes_negative(self):
        from agent_actions.expectations.judge import JudgeBudget

        budget = JudgeBudget(max_calls=1)
        budget.try_acquire()
        budget.try_acquire()
        budget.try_acquire()
        assert budget.remaining == 0

    def test_remaining_decrements_on_each_acquire(self):
        from agent_actions.expectations.judge import JudgeBudget

        budget = JudgeBudget(max_calls=3)
        budget.try_acquire()
        assert budget.remaining == 2

    def test_none_max_calls_is_always_uncapped(self):
        from agent_actions.expectations.judge import JudgeBudget

        budget = JudgeBudget(max_calls=None)
        for _ in range(1000):
            assert budget.try_acquire() is True
        assert budget.remaining is None
