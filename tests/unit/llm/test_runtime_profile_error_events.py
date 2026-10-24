"""A llamafile server that cannot be reached is reported as llamafile, not openai."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import openai
import pytest

from agent_actions.errors import NetworkError
from agent_actions.llm.providers import client_base
from agent_actions.llm.realtime.services.invocation import ClientInvocationService
from agent_actions.logging.events import LLMErrorEvent


class _UnreachableOpenAI:
    def __init__(self, api_key=None, base_url=None, **_: object):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    @staticmethod
    def _create(**_: object):
        raise openai.APIConnectionError(request=httpx.Request("POST", "http://localhost:8080/v1"))


@pytest.fixture
def fired(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-openai-key")
    events: list = []
    with (
        patch("agent_actions.llm.providers.openai.client.OpenAI", _UnreachableOpenAI),
        patch("agent_actions.llm.providers.error_wrapper.fire_event", events.append),
        patch("agent_actions.llm.providers.openai.client.fire_event", events.append),
    ):
        yield events


@pytest.mark.parametrize(
    ("vendor", "json_mode"),
    [("llamafile", True), ("llamafile", False), ("openai", True), ("openai", False)],
)
def test_an_unreachable_server_is_reported_under_the_action_vendor(fired, vendor, json_mode):
    agent_config = {
        "agent_type": "classify_local",
        "model_vendor": vendor,
        "model_name": "local",
        "api_key": "OPENAI_API_KEY",
        "base_url": None,
        "json_mode": json_mode,
    }

    with pytest.raises(NetworkError) as raised:
        ClientInvocationService.invoke_client(
            vendor, agent_config, "classify", {"text": "hello"}, None, "record"
        )

    assert [e.provider for e in fired if isinstance(e, LLMErrorEvent)] == [vendor]
    assert raised.value.context["vendor"] == vendor
    assert str(raised.value).startswith(f"{vendor} ")
