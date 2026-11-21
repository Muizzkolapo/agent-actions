"""With caching on, an Anthropic request marks the end of the text its records share, online and in batch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import anthropic
import pytest

from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
from agent_actions.llm.providers.anthropic.client import AnthropicClient
from tests._support.sdk_http import http_library

# The HTTP library the installed anthropic SDK runs on: httpx, or httpx2 on 1.x.
httpx = http_library(anthropic)

PROMPT = "Summarise the page."
MARK = {"type": "ephemeral"}
MODEL = "claude-sonnet-4-6"
TOOLS = [
    {
        "name": "out",
        "description": "d",
        "input_schema": {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        },
    }
]
SHARED = f"\n<|begin_of_user_instruction|>: {PROMPT}"
CLOSE = " :<|end_of_user_instruction|>\n"

_BATCH_CREATED = {
    "id": "msgbatch_1",
    "type": "message_batch",
    "processing_status": "in_progress",
    "request_counts": {"processing": 1, "succeeded": 0, "errored": 0, "canceled": 0, "expired": 0},
    "created_at": "2026-01-01T00:00:00Z",
    "expires_at": "2026-01-02T00:00:00Z",
    "ended_at": None,
    "archived_at": None,
    "cancel_initiated_at": None,
    "results_url": None,
}


def _record_text(page: str) -> str:
    return f'<|begin_of_text|>: {{"page": "{page}"}} :<|end_of_text|>\n'


def _marks(value: Any) -> list[Any]:
    if isinstance(value, dict):
        found = [value["cache_control"]] if "cache_control" in value else []
        return found + [m for v in value.values() for m in _marks(v)]
    if isinstance(value, list):
        return [m for v in value for m in _marks(v)]
    return []


def _texts(content: str | list[dict[str, Any]]) -> str:
    return content if isinstance(content, str) else "".join(b["text"] for b in content)


def _transport(sent: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.path.endswith("/batches"):
            return httpx.Response(200, json=_BATCH_CREATED)
        body = json.loads(request.content)
        block = (
            {"type": "tool_use", "id": "t", "name": "out", "input": {"a": "x"}}
            if "tools" in body
            else {"type": "text", "text": "x"}
        )
        return httpx.Response(
            200,
            json={
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": MODEL,
                "content": [block],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    return httpx.MockTransport(handler)


def _online(
    caching: bool, page: str, *, json_mode: bool = True, prompt: str = PROMPT
) -> dict[str, Any]:
    sent: list[httpx.Request] = []

    def client(*_args: Any, **_kwargs: Any) -> anthropic.Anthropic:
        return anthropic.Anthropic(
            api_key="sk-ant-test", http_client=httpx.Client(transport=_transport(sent))
        )

    config = {"model_name": MODEL, "enable_prompt_caching": caching}
    with patch("agent_actions.llm.providers.client_base.get_or_create_client", client):
        if json_mode:
            AnthropicClient.call_json(None, config, prompt, {"page": page}, TOOLS)
        else:
            AnthropicClient.call_non_json(None, config, prompt, {"page": page})
    (request,) = sent
    return json.loads(request.content)


def _batch(tmp_path: Path, caching: bool, prompt: str = PROMPT) -> list[dict[str, Any]]:
    sent: list[httpx.Request] = []
    client = BatchClientResolver().get_for_config(
        {
            "agent_type": "summarize",
            "model_vendor": "anthropic",
            "model_name": MODEL,
            "api_key": "TEST_ANTHROPIC_KEY",
            "enable_prompt_caching": caching,
        }
    )
    client.client = anthropic.Anthropic(
        api_key="sk-ant-test", http_client=httpx.Client(transport=_transport(sent))
    )
    rows = [
        {"target_id": page, "content": {"page": page}, "prompt": prompt}
        for page in ("alpha", "beta")
    ]
    agent_config = {
        "model_name": MODEL,
        "json_mode": True,
        "compiled_schema": {"type": "object", "properties": {"a": {"type": "string"}}},
    }
    client.submit_batch(client.prepare_tasks(rows, agent_config), "pages", str(tmp_path))
    (request,) = sent
    return [line["params"] for line in json.loads(request.content)["requests"]]


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "sk-ant-test")


@pytest.mark.parametrize("json_mode", [True, False], ids=["json", "text"])
class TestOnline:
    def test_the_instruction_is_marked_and_the_record_is_not(self, json_mode):
        body = _online(True, "alpha", json_mode=json_mode)

        assert body["messages"] == [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": SHARED, "cache_control": MARK},
                    {"type": "text", "text": CLOSE + _record_text("alpha")},
                ],
            }
        ]

    def test_two_records_send_the_same_marked_block(self, json_mode):
        first = _online(True, "alpha", json_mode=json_mode)["messages"][0]["content"]
        second = _online(True, "beta", json_mode=json_mode)["messages"][0]["content"]

        assert first[0] == second[0]
        assert first[1] != second[1]

    def test_the_model_reads_the_same_text_with_caching_on_or_off(self, json_mode):
        on = _online(True, "alpha", json_mode=json_mode)["messages"][0]["content"]
        off = _online(False, "alpha", json_mode=json_mode)["messages"][0]["content"]

        assert off == SHARED + CLOSE + _record_text("alpha")
        assert _texts(on) == off

    def test_caching_on_sends_one_mark_and_caching_off_sends_none(self, json_mode):
        assert _marks(_online(True, "alpha", json_mode=json_mode)) == [MARK]
        assert _marks(_online(False, "alpha", json_mode=json_mode)) == []


class TestBatch:
    def test_the_instruction_is_marked_and_the_record_is_not(self, tmp_path):
        for params, page in zip(_batch(tmp_path, caching=True), ("alpha", "beta"), strict=True):
            assert "system" not in params
            assert params["messages"] == [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": SHARED, "cache_control": MARK},
                        {"type": "text", "text": CLOSE + _record_text(page)},
                    ],
                }
            ]

    def test_each_request_carries_the_messages_online_sends(self, tmp_path):
        for caching in (True, False):
            batch = _batch(tmp_path, caching=caching)
            online = [_online(caching, page) for page in ("alpha", "beta")]

            assert [p["messages"] for p in batch] == [body["messages"] for body in online]

    def test_each_request_carries_one_mark_with_caching_on_and_none_off(self, tmp_path):
        assert [_marks(p) for p in _batch(tmp_path, caching=True)] == [[MARK], [MARK]]
        assert [_marks(p) for p in _batch(tmp_path, caching=False)] == [[], []]

    def test_the_model_reads_the_same_text_with_caching_on_or_off(self, tmp_path):
        on = _batch(tmp_path, caching=True)
        off = _batch(tmp_path, caching=False)

        assert [_texts(p["messages"][0]["content"]) for p in on] == [
            p["messages"][0]["content"] for p in off
        ]
        assert off[0]["messages"][0]["content"] == SHARED + CLOSE + _record_text("alpha")

    def test_an_empty_prompt_sends_no_system_prompt_and_what_online_sends(self, tmp_path):
        for params, page in zip(
            _batch(tmp_path, caching=True, prompt=""), ("alpha", "beta"), strict=True
        ):
            assert "system" not in params
            assert params["messages"] == _online(True, page, prompt="")["messages"]
