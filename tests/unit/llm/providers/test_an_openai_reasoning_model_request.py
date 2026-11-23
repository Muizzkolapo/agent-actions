"""An OpenAI request a reasoning model (o-series, gpt-5) accepts, and a refusal named.

OpenAI refuses ``max_tokens`` on its reasoning models and takes
``max_completion_tokens`` on every model, so agac sends the action's limit under that
name, online and in batch. A server at a ``base_url`` may know only ``max_tokens`` and
keeps it. An unset temperature is never sent, not even as null. A model that declines
to answer sends its reason as ``refusal``, which the error quotes.

The online requests pass the real SDK with only its transport replaced.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import openai
import pytest

from agent_actions.errors import VendorAPIError
from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.batch_base import BatchTask
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.llm.providers.openai.client import OpenAIClient
from agent_actions.llm.providers.openai.compatible import PROFILE_CLIENTS
from tests._support.sdk_http import http_library

SCHEMA = {
    "name": "answer",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    },
}
REFUSAL = "I can't help with that request."


def _completion(content: str | None, refusal: str | None = None) -> dict[str, Any]:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "o3-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _call(
    method: str,
    config: dict[str, Any],
    answer: dict[str, Any],
    client: type[OpenAIClient] = OpenAIClient,
) -> tuple[Any, dict[str, Any]]:
    """Call *client* through the real SDK; return its result and the JSON body sent."""
    http = http_library(openai)
    sent: list[Any] = []

    def handler(request: Any) -> Any:
        sent.append(request)
        return http.Response(200, json=answer)

    def real_sdk_client(cls: type, api_key: str | None, **kwargs: Any) -> Any:
        transport = http.Client(transport=http.MockTransport(handler))
        return cls(api_key=api_key, max_retries=0, http_client=transport, **kwargs)

    with (
        patch.object(client_base, "get_or_create_client", real_sdk_client),
        patch(
            "agent_actions.output.response.response_builder.ResponseBuilder.record_usage_and_event"
        ),
    ):
        if method == "invoke":
            result = client.invoke(config, "p", {"t": "x"}, None)
        elif method == "call_json":
            result = client.call_json("k", config, "p", {"t": "x"}, SCHEMA)
        else:
            result = client.call_non_json("k", config, "p", {"t": "x"})
    (request,) = sent
    return result, json.loads(request.content)


class TestTheOutputLimit:
    @pytest.mark.parametrize(
        ("method", "answer"),
        [("call_json", _completion('{"ok": true}')), ("call_non_json", _completion("hi"))],
    )
    def test_openai_reads_it_as_max_completion_tokens(self, method, answer):
        _, body = _call(method, {"model_name": "o3-mini", "max_tokens": 300}, answer)

        assert body["max_completion_tokens"] == 300
        assert "max_tokens" not in body

    def test_a_server_at_a_base_url_still_reads_max_tokens(self):
        config = {"model_name": "local", "max_tokens": 300, "base_url": "http://localhost:8080/v1"}

        _, body = _call("call_non_json", config, _completion("hi"))

        assert body["max_tokens"] == 300
        assert "max_completion_tokens" not in body

    def test_a_runtime_profile_still_reads_max_tokens(self):
        config = {"model_name": "local", "max_tokens": 300, "json_mode": False}

        _, body = _call("invoke", config, _completion("hi"), PROFILE_CLIENTS["llamafile"])

        assert body["max_tokens"] == 300
        assert "max_completion_tokens" not in body


def test_an_unset_temperature_is_not_sent_online():
    _, body = _call(
        "call_non_json", {"model_name": "o3-mini", "temperature": None}, _completion("hi")
    )

    assert "temperature" not in body


class TestARefusal:
    def test_a_json_call_fails_its_record_with_the_reason(self, caplog):
        records, _ = _call("call_json", {"model_name": "o3-mini"}, _completion(None, REFUSAL))

        assert records == [
            {"raw_response": "", "_parse_error": f"The model refused to answer: {REFUSAL}"}
        ]
        assert REFUSAL in caplog.text

    def test_a_text_call_raises_with_the_reason(self):
        with pytest.raises(VendorAPIError) as caught:
            _call("call_non_json", {"model_name": "o3-mini"}, _completion(None, REFUSAL))

        assert str(caught.value) == f"The model refused to answer: {REFUSAL}"


def _batch_body(**model_config: Any) -> dict[str, Any]:
    task = BatchTask(
        custom_id="r1",
        prompt="p",
        user_content="{}",
        model_config={"model_name": "o3-mini", "temperature": None, **model_config},
    )
    line = OpenAIBatchClient(api_key="k").format_task_for_provider(task)
    return line["body"]


class TestTheBatchBody:
    def test_it_sends_the_limit_as_max_completion_tokens(self):
        body = _batch_body(max_tokens=300)

        assert body["max_completion_tokens"] == 300
        assert "max_tokens" not in body

    def test_it_sends_no_null_temperature(self):
        body = _batch_body(model_name="gpt-4o-mini")

        assert "temperature" not in body

    @pytest.mark.parametrize(("model", "temperature"), [("gpt-4o-mini", 0.2), ("gpt-5-mini", 1)])
    def test_it_sends_the_temperature_the_action_set(self, model, temperature):
        assert _batch_body(model_name=model, temperature=temperature)["temperature"] == temperature


def test_a_batch_refusal_fails_its_record_with_the_reason():
    """An answered line with no answer in it: the reason is its error, and it has no content."""
    line = {
        "custom_id": "r1",
        "response": {"status_code": 200, "body": _completion(None, REFUSAL)},
    }

    result = OpenAIBatchClient(api_key="k").parse_provider_response(line)

    assert result.content is None
    assert result.error == f"The model refused to answer: {REFUSAL}"
