"""A Cohere call through the real SDK: the schema field it sends and the answer it reads."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import cohere
import httpx
import pytest

from agent_actions.errors import VendorAPIError
from agent_actions.llm.providers.cohere.client import CohereClient

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
THINKING = {"type": "thinking", "thinking": "Let me work it out."}


def _answer(*content: dict[str, Any], finish_reason: str = "COMPLETE") -> dict[str, Any]:
    return {
        "id": "c1",
        "finish_reason": finish_reason,
        "message": {"role": "assistant", "content": list(content)},
        "usage": {"tokens": {"input_tokens": 1, "output_tokens": 1}},
    }


def _call(method: str, answer: dict[str, Any], *args: Any) -> tuple[Any, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=answer)

    real = cohere.ClientV2

    def client_on_mock_wire(**kwargs: Any) -> cohere.ClientV2:
        return real(**kwargs, httpx_client=httpx.Client(transport=httpx.MockTransport(handler)))

    with (
        patch("agent_actions.llm.providers.cohere.client.cohere.ClientV2", client_on_mock_wire),
        patch(
            "agent_actions.output.response.response_builder.ResponseBuilder.record_usage_and_event"
        ),
    ):
        result = getattr(CohereClient, method)("k", {"model_name": "m"}, "p", {"t": "x"}, *args)
    return result, sent


def test_the_schema_goes_in_json_schema():
    _, sent = _call("call_json", _answer({"type": "text", "text": '{"answer": "4"}'}), SCHEMA)

    assert sent[0]["response_format"] == {"type": "json_object", "json_schema": SCHEMA}


def test_a_json_answer_after_a_thinking_item_is_read():
    answer = _answer(THINKING, {"type": "text", "text": '{"answer": "4"}'})

    result, _ = _call("call_json", answer, SCHEMA)

    assert result == [{"answer": "4"}]


def test_a_text_answer_after_a_thinking_item_is_read():
    result, _ = _call("call_non_json", _answer(THINKING, {"type": "text", "text": "four"}))

    assert result == [{"raw_response": "four"}]


@pytest.mark.parametrize("method,args", [("call_json", (SCHEMA,)), ("call_non_json", ())])
def test_only_thinking_is_an_empty_answer(method, args):
    with pytest.raises(VendorAPIError, match="Empty response content"):
        _call(method, _answer(THINKING, finish_reason="MAX_TOKENS"), *args)
