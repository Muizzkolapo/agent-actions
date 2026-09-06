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
    """What a JSON-mode provider returns: the verdict, already parsed."""
    return [{"passed": passed, "reason": reason}]


def _raw_result(text: str):
    """What a provider returns when the reply did not parse as JSON."""
    return [{"raw_response": text}]


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
        with patch(INVOKE, return_value=_raw_result("not json at all")):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "not a verdict object" in detail

    def test_missing_passed_key_is_a_failure(self):
        with patch(INVOKE, return_value=_raw_result(json.dumps({"reason": "no verdict field"}))):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "boolean 'passed'" in detail

    def test_non_boolean_passed_value_is_a_failure(self):
        with patch(INVOKE, return_value=_raw_result(json.dumps({"passed": "yes"}))):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False

    def test_empty_result_is_a_failure(self):
        with patch(INVOKE, return_value=[]):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "empty" in detail


class TestTheVerdictDialectsAccepted:
    """A verdict is scored on the value under test, not on the judge's reply syntax.

    Judge models answer in one of two faithful serializations — JSON or a Python
    literal — sometimes inside a code fence. All four are the same verdict and
    must be read as one.
    """

    PYTHON_LITERAL_PASS = (
        "{'passed': True, 'reason': 'Concrete situation with goal and constraint'}"
    )
    PYTHON_LITERAL_FAIL = "{'passed': False, 'reason': 'It is a definition prompt'}"
    FENCED = '```json\n{"passed": true, "reason": "reads as a scenario"}\n```'
    FENCED_PYTHON_LITERAL = "```\n{'passed': False, 'reason': 'a definition prompt'}\n```"

    def test_python_literal_pass_is_a_pass(self):
        with patch(INVOKE, return_value=_raw_result(self.PYTHON_LITERAL_PASS)):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is True
        assert detail == "Concrete situation with goal and constraint"

    def test_python_literal_fail_reports_the_judges_reason(self):
        with patch(INVOKE, return_value=_raw_result(self.PYTHON_LITERAL_FAIL)):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert detail == "It is a definition prompt"

    def test_fenced_verdict_is_read(self):
        with patch(INVOKE, return_value=_raw_result(self.FENCED)):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is True
        assert detail == "reads as a scenario"

    def test_fenced_python_literal_is_read(self):
        with patch(INVOKE, return_value=_raw_result(self.FENCED_PYTHON_LITERAL)):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert detail == "a definition prompt"

    def test_votes_are_tallied_across_dialects(self):
        """The majority runs on read verdicts, so a dialect no longer costs a vote."""
        from agent_actions.expectations.judge import invoke_judge_with_votes

        replies = [
            _raw_result(self.PYTHON_LITERAL_PASS),
            _raw_result(self.FENCED),
            _raw_result("I am not going to answer that."),
        ]
        with patch(INVOKE, side_effect=replies):
            passed, detail = invoke_judge_with_votes(_agent_config(), "rule", "value", votes=3)
        assert passed is True
        assert detail == "2/3 judge votes passed"


class TestTheEnvelopesProvidersActuallyReturn:
    """`invoke_client` hands back one of two shapes, and neither is `content`.

    Under `json_mode` (the default) the provider has already parsed the reply and
    returns the verdict object itself. Otherwise it wraps the raw text under the
    configured output field. A reader that looks for keys no provider writes
    falls through to `str(first)` and reads the repr of an object it was handed.
    """

    def test_a_verdict_the_provider_already_parsed_is_used_as_is(self):
        with patch(INVOKE, return_value=[{"passed": True, "reason": "specific enough"}]):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is True
        assert detail == "specific enough"

    def test_a_parsed_failing_verdict_keeps_its_reason(self):
        with patch(INVOKE, return_value=[{"passed": False, "reason": "too generic"}]):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert detail == "too generic"

    def test_a_verdict_under_the_output_field_is_read(self):
        with patch(INVOKE, return_value=_raw_result('{"passed": true, "reason": "ok"}')):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is True
        assert detail == "ok"

    def test_an_empty_output_field_fails_closed(self):
        with patch(INVOKE, return_value=[{"raw_response": "", "_parse_error": "Empty response"}]):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "not a verdict object" in detail

    def test_a_parsed_object_that_is_not_a_verdict_fails_closed(self):
        with patch(INVOKE, return_value=[{"verdict": "pass", "reason": "nested"}]):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "boolean 'passed'" in detail


class TestTheJudgeAsksForTextSoItDoesItsOwnReading:
    """The verdict must reach `_read_verdict`, not a provider's parser.

    Under `json_mode` the provider parses the reply itself — through the
    best-effort reader that scavenges an object out of prose. A judge that
    inherits the action's `json_mode: true` therefore never sees the text, and
    the strict reading below it is dead code on the default path.
    """

    def test_the_judge_call_does_not_inherit_json_mode(self):
        with patch(INVOKE, return_value=_raw_result('{"passed": true, "reason": "ok"}')) as mock:
            invoke_judge(_agent_config(json_mode=True), "rule", "value")
        assert mock.call_args.kwargs["agent_config"]["json_mode"] is False

    def test_the_caller_config_is_not_mutated(self):
        config = _agent_config(json_mode=True)
        with patch(INVOKE, return_value=_raw_result('{"passed": true, "reason": "ok"}')):
            invoke_judge(config, "rule", "value")
        assert config["json_mode"] is True


class TestAVerdictIsNeverScavengedOutOfProse:
    """The reply is read whole or refused.

    ``passed`` is the terminal boolean of a validation gate — unlike a provider
    response, nothing downstream re-checks it. A best-effort reader that lifts
    the first object-shaped fragment out of surrounding prose therefore inverts
    verdicts: the prompt this module sends shows the model the exact object it
    should emit, so a judge that argues for failure while quoting that example
    would be read as a pass.
    """

    def test_prose_quoting_the_requested_format_is_not_a_verdict(self):
        reply = (
            "The value fails the rule: the options are generic restatements. "
            'For reference, a passing reply would look like {"passed": true, '
            '"reason": "one sentence"}.'
        )
        with patch(INVOKE, return_value=_raw_result(reply)):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "not a verdict object" in detail

    def test_a_verdict_superseded_by_prose_is_not_a_verdict(self):
        reply = (
            'Draft: {"passed": true, "reason": "seems specific"}\n'
            "Correction: on closer reading it is generic, so the verdict is fail."
        )
        with patch(INVOKE, return_value=_raw_result(reply)):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "not a verdict object" in detail

    def test_fragments_are_not_merged_into_a_verdict(self):
        reply = 'It fails because the JSON {"foo": 1 is broken and passed: true is not right'
        with patch(INVOKE, return_value=_raw_result(reply)):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "not a verdict object" in detail

    def test_a_list_is_not_a_verdict(self):
        with patch(INVOKE, return_value=_raw_result('[{"passed": true, "reason": "ok"}]')):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "not a verdict object" in detail

    def test_two_verdicts_are_not_resolved_by_taking_one(self):
        reply = '{"passed": true, "reason": "first"}\n{"passed": false, "reason": "second"}'
        with patch(INVOKE, return_value=_raw_result(reply)):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "not a verdict object" in detail

    def test_a_truncated_verdict_fails_closed(self):
        with patch(INVOKE, return_value=_raw_result('{"passed": true, "reason": "the val')):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "not a verdict object" in detail

    def test_prose_with_no_object_fails_closed(self):
        with patch(INVOKE, return_value=_raw_result("The value is fine, I would pass it.")):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "not a verdict object" in detail

    def test_empty_reply_fails_closed(self):
        with patch(INVOKE, return_value=_raw_result("")):
            passed, detail = invoke_judge(_agent_config(), "rule", "value")
        assert passed is False
        assert "not a verdict object" in detail


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
