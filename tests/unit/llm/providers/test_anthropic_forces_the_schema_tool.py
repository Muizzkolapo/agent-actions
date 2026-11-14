"""In JSON mode the Anthropic request forces the schema tool, and a large budget streams.

A model left to choose could answer in text, failing the record with
``No tool_use block in response``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.anthropic.client import AnthropicClient

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
    def test_the_schema_tool_is_forced(self):
        assert _args()["tool_choice"] == {"type": "tool", "name": "quiz"}

    def test_a_workflow_tool_choice_wins(self):
        args = _args({"tool_choice": {"type": "auto"}})

        assert args["tool_choice"] == {"type": "auto"}

    def test_thinking_leaves_the_choice_to_the_model(self):
        """The API refuses a forced tool while thinking is on."""
        args = _args({"thinking": {"type": "enabled", "budget_tokens": 2048}})

        assert "tool_choice" not in args

    def test_disabled_thinking_still_forces_the_tool(self):
        args = _args({"thinking": {"type": "disabled"}})

        assert args["tool_choice"] == {"type": "tool", "name": "quiz"}

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
