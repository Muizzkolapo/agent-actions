"""In JSON mode an online Anthropic request offers the schema tool without forcing it.

Forced (#1774), claude-haiku-5-5 returned a nested array as one JSON string in the first
field, and repair gave back the same shape (#1781). A workflow can still force it. A large
budget streams.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.anthropic.client import AnthropicClient
from agent_actions.llm.providers.generation_params import VendorParamSpec

SCHEMA = [{"name": "quiz", "description": "", "input_schema": {"type": "object"}}]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})
    with patch(
        "agent_actions.output.response.response_builder.ResponseBuilder.record_usage_and_event"
    ):
        yield


def _args(vendor_params: dict[str, Any] | None = None, schema: Any = SCHEMA) -> dict[str, Any]:
    config = {"vendor_params": vendor_params} if vendor_params else {}
    return AnthropicClient._build_api_args("m", [], schema, config)


class TestToolChoice:
    def test_the_schema_tool_is_offered_and_not_forced(self):
        args = _args()

        assert args["tools"] == SCHEMA
        assert "tool_choice" not in args

    def test_a_workflow_can_force_the_tool(self):
        forced = {"type": "tool", "name": "quiz"}

        assert _args({"tool_choice": forced})["tool_choice"] == forced

    def test_disabled_thinking_does_not_force_it_either(self):
        assert "tool_choice" not in _args({"thinking": {"type": "disabled"}})

    def test_text_mode_sets_no_tool_choice(self):
        assert "tool_choice" not in _args(schema=None)


def _run(config: dict[str, Any]) -> MagicMock:
    with patch("anthropic.Anthropic") as sdk:
        message = MagicMock(content=[SimpleNamespace(text="ok")], stop_reason="end_turn")
        sdk.return_value.messages.create.return_value = message
        stream = sdk.return_value.messages.stream.return_value.__enter__.return_value
        stream.get_final_message.return_value = message
        AnthropicClient.call_non_json("k", {"model_name": "m", **config}, "p", {"t": "x"})
    return sdk.return_value.messages


class TestStreaming:
    def test_a_budget_the_sdk_would_refuse_unstreamed_is_streamed(self):
        messages = _run({"max_tokens": 32_000})

        messages.create.assert_not_called()
        assert messages.stream.call_args.kwargs["max_tokens"] == 32_000
        assert messages.stream.call_args.kwargs["timeout"].read == 600

    def test_a_budget_below_the_limit_is_not_streamed(self):
        messages = _run({"max_tokens": 16_000})

        messages.stream.assert_not_called()
        assert messages.create.call_args.kwargs["max_tokens"] == 16_000


def _answer(text: str, stop_reason: str = "end_turn") -> list[dict[str, Any]]:
    with patch("anthropic.Anthropic") as sdk:
        sdk.return_value.messages.create.return_value = MagicMock(
            content=[SimpleNamespace(text=text)], stop_reason=stop_reason
        )
        return AnthropicClient.call_json("k", {"model_name": "m"}, "p", {"t": "x"}, SCHEMA)


class TestAnAnswerWrittenAsText:
    """Offered the tool, the model can answer in text; a finished JSON answer is read (#1781)."""

    def test_a_fenced_json_answer_is_read(self):
        text = '```json\n{"concepts": [{"concept": "tides", "weight": 2}]}\n```'

        assert _answer(text) == [{"concepts": [{"concept": "tides", "weight": 2}]}]

    def test_a_bare_json_answer_is_read(self):
        assert _answer('{"a": 1}') == [{"a": 1}]

    def test_a_list_of_objects_is_read(self):
        assert _answer('[{"a": 1}, {"a": 2}]') == [{"a": 1}, {"a": 2}]

    def test_prose_stays_a_parse_error_for_repair(self):
        with patch("agent_actions.llm.providers.anthropic.client.fire_event") as fire:
            (result,) = _answer("I cannot help with that.")

        assert result["raw_response"] == "I cannot help with that."
        assert "No tool_use block in response (stop_reason=end_turn)" in result["_parse_error"]
        (event,) = [
            call.args[0] for call in fire.call_args_list if hasattr(call.args[0], "error_type")
        ]
        assert event.error_type == "EmptyResponse"

    def test_a_json_answer_read_from_text_fires_no_error_event(self):
        with patch("agent_actions.llm.providers.anthropic.client.fire_event") as fire:
            _answer('```json\n{"a": 1}\n```')

        assert not [c for c in fire.call_args_list if getattr(c.args[0], "error_type", None)]

    def test_a_tool_answer_is_returned_as_before(self):
        with patch("anthropic.Anthropic") as sdk:
            sdk.return_value.messages.create.return_value = MagicMock(
                content=[SimpleNamespace(input={"a": 1})], stop_reason="tool_use"
            )
            result = AnthropicClient.call_json("k", {"model_name": "m"}, "p", {"t": "x"}, SCHEMA)

        assert result == [{"a": 1}]

    def test_a_cut_off_answer_is_not_guessed_at(self):
        (result,) = _answer('```json\n{"concepts": [{"concept": "ti', stop_reason="max_tokens")

        assert "stop_reason=max_tokens" in result["_parse_error"]


class TestAKeyTheSdkDoesNotTake:
    """anthropic 1.x dropped temperature from create; agac's setting goes in extra_body."""

    def test_it_moves_into_extra_body(self):
        spec = VendorParamSpec(accepted=frozenset({"model", "messages", "extra_body"}))

        fitted = spec.fit({"model": "m", "messages": [], "temperature": 0.3, "top_p": 0.9})

        assert fitted == {
            "model": "m",
            "messages": [],
            "extra_body": {"temperature": 0.3, "top_p": 0.9},
        }

    def test_a_workflow_extra_body_keeps_its_own_values(self):
        spec = VendorParamSpec(accepted=frozenset({"model", "extra_body"}))

        fitted = spec.fit({"model": "m", "temperature": 0.3, "extra_body": {"temperature": 1}})

        assert fitted["extra_body"] == {"temperature": 1}

    def test_a_key_the_sdk_takes_stays_where_it_is(self):
        args = _args()

        assert "extra_body" not in args or "max_tokens" not in args["extra_body"]
        assert args["max_tokens"] == 4096
