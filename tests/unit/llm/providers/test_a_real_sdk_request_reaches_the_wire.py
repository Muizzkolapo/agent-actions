"""Each client's request passes the real SDK and reaches the wire with what agac set.

The other provider tests replace the SDK with a mock, so an argument the SDK itself
refuses, such as an ``httpx.Timeout`` given to an SDK on httpx2 (#1781), passed them.
Here the SDK is real and only its transport is replaced, built from whichever HTTP
library the installed SDK runs on. CI runs this file on the newest SDK versions the
pins allow, as well as on the locked ones.
"""

from __future__ import annotations

import importlib
import json
from types import ModuleType
from typing import Any
from unittest.mock import patch

import pytest

from agent_actions.llm.providers import client_base
from tests._support.sdk_http import http_library

ANTHROPIC_MESSAGE = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "m",
    "content": [{"type": "text", "text": "hi"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}
CHAT_COMPLETION = {
    "id": "c1",
    "object": "chat.completion",
    "created": 0,
    "model": "m",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


class _Wire:
    """A transport that records each request and answers with *body*."""

    def __init__(self, sdk: ModuleType, body: dict[str, Any]):
        self.http = http_library(sdk)
        self.body = body
        self.requests: list[Any] = []

    def handler(self, request: Any) -> Any:
        self.requests.append(request)
        return self.http.Response(200, json=self.body)

    def client(self) -> Any:
        return self.http.Client(transport=self.http.MockTransport(self.handler))

    @property
    def sent(self) -> dict[str, Any]:
        (request,) = self.requests
        return json.loads(request.content)

    @property
    def timeout(self) -> dict[str, Any]:
        (request,) = self.requests
        return request.extensions["timeout"]


def _send(sdk_name: str, client_path: str, body: dict[str, Any], config: dict[str, Any]) -> _Wire:
    sdk = importlib.import_module(sdk_name)
    wire = _Wire(sdk, body)

    def real_sdk_client(cls: type, api_key: str | None, **kwargs: Any) -> Any:
        return cls(api_key=api_key, max_retries=0, http_client=wire.client(), **kwargs)

    module_path, class_name = client_path.split(":")
    client = getattr(importlib.import_module(module_path), class_name)
    with (
        patch.object(client_base, "get_or_create_client", real_sdk_client),
        patch(
            "agent_actions.output.response.response_builder.ResponseBuilder.record_usage_and_event"
        ),
    ):
        client.call_non_json("k", {"model_name": "m", **config}, "p", {"t": "x"})
    return wire


# vendor -> (SDK module, agac client, the vendor's answer, a parameter only vendor_params sends)
VENDORS = {
    "anthropic": (
        "anthropic",
        "agent_actions.llm.providers.anthropic.client:AnthropicClient",
        ANTHROPIC_MESSAGE,
        {"metadata": {"user_id": "u1"}},
    ),
    "openai": (
        "openai",
        "agent_actions.llm.providers.openai.client:OpenAIClient",
        CHAT_COMPLETION,
        {"seed": 7},
    ),
    "groq": (
        "groq",
        "agent_actions.llm.providers.groq.client:GroqClient",
        CHAT_COMPLETION,
        {"seed": 7},
    ),
}


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_the_request_reaches_the_wire_with_its_timeout_and_vendor_params(vendor):
    sdk_name, client_path, body, vendor_params = VENDORS[vendor]

    wire = _send(
        sdk_name,
        client_path,
        body,
        {"temperature": 0.3, "request_timeout": 42, "vendor_params": vendor_params},
    )

    assert wire.sent["model"] == "m"
    assert wire.sent["temperature"] == 0.3
    assert {key: wire.sent[key] for key in vendor_params} == vendor_params
    assert wire.timeout["read"] == 42
    assert wire.timeout["connect"] == 5.0


def test_a_json_mode_anthropic_request_offers_the_schema_tool_without_forcing_it():
    tool = {"name": "quiz", "description": "", "input_schema": {"type": "object"}}
    answer = {
        **ANTHROPIC_MESSAGE,
        "content": [{"type": "tool_use", "id": "t1", "name": "quiz", "input": {"a": 1}}],
    }
    sdk = importlib.import_module("anthropic")
    wire = _Wire(sdk, answer)

    def real_sdk_client(cls: type, api_key: str | None, **kwargs: Any) -> Any:
        return cls(api_key=api_key, max_retries=0, http_client=wire.client(), **kwargs)

    from agent_actions.llm.providers.anthropic.client import AnthropicClient

    with (
        patch.object(client_base, "get_or_create_client", real_sdk_client),
        patch(
            "agent_actions.output.response.response_builder.ResponseBuilder.record_usage_and_event"
        ),
    ):
        result = AnthropicClient.call_json("k", {"model_name": "m"}, "p", {"t": "x"}, [tool])

    assert result == [{"a": 1}]
    assert wire.sent["tools"][0]["name"] == "quiz"
    assert "tool_choice" not in wire.sent
