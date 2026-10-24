"""A runtime profile vendor's events name that vendor, and its usage still counts."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.providers import client_base
from agent_actions.llm.realtime.services.invocation import ClientInvocationService
from agent_actions.logging.events import LLMErrorEvent, LLMRequestEvent, LLMResponseEvent


def _response(content: str | None):
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(prompt_tokens=12, completion_tokens=7, total_tokens=19)
    response.model = "local"
    return response


class _FakeOpenAI:
    content: str | None = json.dumps({"answer": "ok"})

    def __init__(self, api_key=None, base_url=None, **_: object):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_: _response(_FakeOpenAI.content))
        )


@pytest.fixture
def events(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-openai-key")
    _FakeOpenAI.content = json.dumps({"answer": "ok"})
    fired: list = []
    with (
        patch("agent_actions.llm.providers.openai.client.OpenAI", _FakeOpenAI),
        patch("agent_actions.llm.providers.openai.client.fire_event", fired.append),
        patch("agent_actions.output.response.response_builder.fire_event", fired.append),
    ):
        yield fired


def _invoke(vendor: str, json_mode: bool = True, **config: object):
    agent_config = {
        "agent_type": "classify_local",
        "model_vendor": vendor,
        "model_name": "local",
        "api_key": "OPENAI_API_KEY",
        "base_url": None,
        "json_mode": json_mode,
        **config,
    }
    return ClientInvocationService.invoke_client(
        vendor, agent_config, "classify", {"text": "hello"}, None, "record"
    )


def _of(fired, kind):
    return [e for e in fired if isinstance(e, kind)]


@pytest.mark.parametrize("json_mode", [True, False])
def test_a_llamafile_call_names_llamafile_in_its_events(events, json_mode):
    _invoke("llamafile", json_mode=json_mode)

    assert [e.provider for e in _of(events, LLMRequestEvent)] == ["llamafile"]
    responses = _of(events, LLMResponseEvent)
    assert [(e.provider, e.prompt_tokens, e.completion_tokens) for e in responses] == [
        ("llamafile", 12, 7)
    ]


@pytest.mark.parametrize("json_mode", [True, False])
def test_an_openai_call_still_names_openai(events, json_mode):
    _invoke("openai", json_mode=json_mode, model_name="gpt-4o-mini")

    assert [e.provider for e in _of(events, LLMRequestEvent)] == ["openai"]
    assert [(e.provider, e.prompt_tokens) for e in _of(events, LLMResponseEvent)] == [
        ("openai", 12)
    ]


def test_an_empty_llamafile_response_names_llamafile_in_its_error_event(events):
    _FakeOpenAI.content = None

    _invoke("llamafile")

    assert [e.provider for e in _of(events, LLMErrorEvent)] == ["llamafile"]
