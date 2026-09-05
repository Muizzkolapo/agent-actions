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
        assert "not valid JSON" in detail

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
