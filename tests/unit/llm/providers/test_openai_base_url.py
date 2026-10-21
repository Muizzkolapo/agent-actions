"""The openai vendor sends each action to the base_url that action configured.

Every fake server below answers with the URL it was built for, so an
assertion on the returned row is an assertion on which server was reached.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.client_base import get_or_create_client
from agent_actions.llm.providers.openai.client import OpenAIClient

LOCAL_A = "http://localhost:8089/v1"
LOCAL_B = "http://localhost:9099/v1"
DEFAULT = "default"


def _response(content: str):
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    response.model = "local"
    return response


class _FakeOpenAI:
    """SDK stand-in. Each instance answers with the URL it was constructed for."""

    def __init__(self, api_key=None, base_url=None, **_: object):
        self.api_key = api_key
        self.base_url = base_url
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_: object):
        return _response(json.dumps({"served_by": self.base_url or DEFAULT}))


@pytest.fixture(autouse=True)
def _isolated_client_cache(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})
    with patch("agent_actions.llm.providers.openai.client.OpenAI", _FakeOpenAI):
        yield


def _call_json(agent_config: dict) -> dict:
    rows = OpenAIClient.call_json(
        api_key="shared-key",
        agent_config=agent_config,
        prompt_config="classify",
        context_data={"text": "hello"},
        schema=None,
    )
    return rows[0]


class TestCallJsonRouting:
    def test_two_actions_same_key_different_base_url_reach_their_own_servers(self):
        row_a = _call_json({"model_name": "local", "base_url": LOCAL_A})
        row_b = _call_json({"model_name": "local", "base_url": LOCAL_B})

        assert row_a["served_by"] == LOCAL_A
        assert row_b["served_by"] == LOCAL_B

    def test_action_without_base_url_uses_the_default_endpoint(self):
        row = _call_json({"model_name": "gpt-4o-mini"})

        assert row["served_by"] == DEFAULT

    def test_local_action_then_cloud_action_with_the_same_key(self):
        local = _call_json({"model_name": "local", "base_url": LOCAL_A})
        cloud = _call_json({"model_name": "gpt-4o-mini"})

        assert local["served_by"] == LOCAL_A
        assert cloud["served_by"] == DEFAULT

    def test_cloud_action_then_local_action_with_the_same_key(self):
        cloud = _call_json({"model_name": "gpt-4o-mini"})
        local = _call_json({"model_name": "local", "base_url": LOCAL_A})

        assert cloud["served_by"] == DEFAULT
        assert local["served_by"] == LOCAL_A


class TestCallNonJsonRouting:
    def test_non_json_action_reaches_its_base_url(self):
        rows = OpenAIClient.call_non_json(
            api_key="shared-key",
            agent_config={"model_name": "local", "base_url": LOCAL_A},
            prompt_config="say hello",
            context_data={},
        )

        assert json.loads(rows[0]["raw_response"]) == {"served_by": LOCAL_A}

    def test_non_json_action_without_base_url_uses_the_default_endpoint(self):
        rows = OpenAIClient.call_non_json(
            api_key="shared-key",
            agent_config={"model_name": "gpt-4o-mini"},
            prompt_config="say hello",
            context_data={},
        )

        assert json.loads(rows[0]["raw_response"]) == {"served_by": DEFAULT}


class TestClientCache:
    def test_same_key_different_url_gets_a_separate_client(self):
        first = get_or_create_client(_FakeOpenAI, "shared-key", base_url=LOCAL_A)
        second = get_or_create_client(_FakeOpenAI, "shared-key", base_url=LOCAL_B)

        assert first.base_url == LOCAL_A
        assert second.base_url == LOCAL_B

    def test_same_key_same_url_reuses_the_client(self):
        first = get_or_create_client(_FakeOpenAI, "shared-key", base_url=LOCAL_A)
        second = get_or_create_client(_FakeOpenAI, "shared-key", base_url=LOCAL_A)

        assert first is second

    def test_url_and_no_url_are_different_clients(self):
        with_url = get_or_create_client(_FakeOpenAI, "shared-key", base_url=LOCAL_A)
        without_url = get_or_create_client(_FakeOpenAI, "shared-key")

        assert with_url.base_url == LOCAL_A
        assert without_url.base_url is None


class TestCapabilities:
    def test_base_url_is_a_declared_optional_field(self):
        assert "base_url" in OpenAIClient.CAPABILITIES["optional_fields"]
