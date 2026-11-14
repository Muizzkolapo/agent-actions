"""An action's `vendor_params` reach each batch request line, as they reach an online request.

A batch line is the request's JSON body, so `extra_body` joins it at the top level.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient
from agent_actions.llm.providers.groq.batch_client import GroqBatchClient
from agent_actions.llm.providers.ollama.batch_client import OllamaBatchClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient

ROW = {"target_id": "r1", "content": {"t": "x"}, "prompt": "p"}
TOOL = [{"name": "quiz", "description": "", "input_schema": {"properties": {"a": {}}}}]


def _bare(cls: type, **attrs: Any) -> Any:
    client = cls.__new__(cls)
    for key, value in attrs.items():
        setattr(client, key, value)
    return client


def _line(client: Any, vendor_params: dict | None, schema: Any = None) -> dict[str, Any]:
    config: dict[str, Any] = {"model_name": "m", "json_mode": schema is not None}
    if schema is not None:
        config["compiled_schema"] = schema
    if vendor_params is not None:
        config["vendor_params"] = vendor_params
    (task,) = client.prepare_tasks([dict(ROW)], config)
    return task


@pytest.mark.parametrize("cls", [OpenAIBatchClient, GroqBatchClient], ids=["openai", "groq"])
class TestOpenAIShapedBodies:
    def test_vendor_params_join_the_body(self, cls):
        body = _line(_bare(cls), {"seed": 7, "reasoning_effort": "low"})["body"]

        assert (body["seed"], body["reasoning_effort"]) == (7, "low")

    def test_extra_body_joins_the_body_and_headers_have_nowhere_to_go(self, cls):
        body = _line(
            _bare(cls), {"extra_body": {"service_tier": "flex"}, "extra_headers": {"x": "1"}}
        )["body"]

        assert body["service_tier"] == "flex"
        assert "extra_body" not in body
        assert "extra_headers" not in body

    def test_a_reserved_key_cannot_change_the_model(self, cls):
        assert _line(_bare(cls), {"model": "other"})["body"]["model"] == "m"


class TestAnthropicBatch:
    def _client(self) -> AnthropicBatchClient:
        return _bare(AnthropicBatchClient, enable_prompt_caching=False)

    def test_vendor_params_join_the_params(self):
        params = _line(self._client(), {"thinking": {"type": "disabled"}, "top_k": 5})["params"]

        assert (params["thinking"], params["top_k"]) == ({"type": "disabled"}, 5)

    def test_the_schema_tool_is_forced(self):
        params = _line(self._client(), None, TOOL)["params"]

        assert params["tool_choice"] == {"type": "tool", "name": "quiz"}

    def test_thinking_leaves_the_tool_choice_to_the_model(self):
        params = _line(
            self._client(), {"thinking": {"type": "enabled", "budget_tokens": 2048}}, TOOL
        )["params"]

        assert "tool_choice" not in params

    def test_a_workflow_tool_choice_wins(self):
        params = _line(self._client(), {"tool_choice": {"type": "any"}}, TOOL)["params"]

        assert params["tool_choice"] == {"type": "any"}


class TestGeminiBatch:
    def test_generation_settings_go_in_generation_config(self):
        request = _line(_bare(GeminiBatchClient), {"thinking_config": {"thinking_budget": 0}})[
            "request"
        ]

        assert request["generation_config"]["thinking_config"] == {"thinking_budget": 0}

    def test_request_fields_go_beside_it(self):
        request = _line(_bare(GeminiBatchClient), {"safety_settings": [{"x": 1}]})["request"]

        assert request["safety_settings"] == [{"x": 1}]
        assert "safety_settings" not in request.get("generation_config", {})


class TestOllamaBatch:
    def test_vendor_params_reach_the_chat_call(self):
        client = OllamaBatchClient(base_url="http://localhost:11434")
        client.client = MagicMock()
        client.client.chat.return_value = {
            "model": "m",
            "message": {"role": "assistant", "content": "ok"},
            "done": True,
        }
        task = _line(client, {"think": False, "options": {"num_ctx": 8192}})

        client._process_single_task(task, 0, 1)

        sent = client.client.chat.call_args.kwargs
        assert sent["think"] is False
        assert sent["options"]["num_ctx"] == 8192
        assert "temperature" in sent["options"]
