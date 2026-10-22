"""A named runtime vendor (llamafile) reaches its own server through the OpenAI client.

Every fake SDK client below records the URL and key it was built with and the
request it was sent, so each assertion is about which server was reached and
what it received.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.llm.providers import client_base
from agent_actions.llm.realtime.services.invocation import ClientInvocationService
from agent_actions.output.response.context_data import _compile_schema_for_vendor
from agent_actions.output.response.expander_validation import validate_vendor_exists
from agent_actions.output.response.vendor_compilation import compile_unified_schema

LLAMAFILE_DEFAULT = "http://localhost:8080/v1"
OPENAI_DEFAULT = "openai-default"
SCHEMA = {
    "name": "probe_reply",
    "fields": [{"id": "answer", "type": "string"}],
    "required_by_default": True,
}


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
    """SDK stand-in that answers with the URL and key it was built with."""

    requests: list[dict] = []

    def __init__(self, api_key=None, base_url=None, **_: object):
        self.api_key = api_key
        self.base_url = base_url
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: object):
        _FakeOpenAI.requests.append(kwargs)
        return _response(
            json.dumps({"served_by": self.base_url or OPENAI_DEFAULT, "key": self.api_key})
        )


@pytest.fixture(autouse=True)
def _fake_sdk(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-openai-key")
    _FakeOpenAI.requests = []
    with patch("agent_actions.llm.providers.openai.client.OpenAI", _FakeOpenAI):
        yield


def _invoke(vendor: str, schema: dict | None = None, **config: object) -> dict:
    agent_config = {
        "agent_type": "classify_local",
        "model_vendor": vendor,
        "model_name": "local",
        "api_key": "OPENAI_API_KEY",
        "base_url": None,
        "json_mode": True,
        **config,
    }
    rows = ClientInvocationService.invoke_client(
        vendor, agent_config, "classify", {"text": "hello"}, schema, "record"
    )
    return rows[0]


class TestRouting:
    def test_a_llamafile_action_with_no_base_url_reaches_the_local_default(self):
        row = _invoke("llamafile")

        assert row["served_by"] == LLAMAFILE_DEFAULT

    def test_a_llamafile_action_with_a_base_url_reaches_that_url(self):
        row = _invoke("llamafile", base_url="http://localhost:9099/v1")

        assert row["served_by"] == "http://localhost:9099/v1"

    def test_a_llamafile_and_an_openai_action_in_one_run_reach_their_own_servers(self):
        local = _invoke("llamafile")
        cloud = _invoke("openai", model_name="gpt-4o-mini")

        assert local["served_by"] == LLAMAFILE_DEFAULT
        assert cloud["served_by"] == OPENAI_DEFAULT


class TestKey:
    def test_a_llamafile_action_never_sends_the_inherited_openai_key(self):
        row = _invoke("llamafile")

        assert row["key"] == "no-key-required"

    def test_a_llamafile_action_needs_no_key_in_the_environment(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY")

        row = _invoke("llamafile", api_key=None)

        assert row["key"] == "no-key-required"

    def test_an_openai_action_still_sends_its_own_key(self):
        row = _invoke("openai", model_name="gpt-4o-mini")

        assert row["key"] == "sk-real-openai-key"


class TestSchemaShape:
    def test_a_llamafile_schema_compiles_to_the_openai_shape(self):
        compiled = _compile_schema_for_vendor(SCHEMA, "llamafile", "probe_reply")

        assert compiled == compile_unified_schema(SCHEMA, "openai")
        assert compiled["schema"]["properties"] == {"answer": {"type": "string"}}

    def test_the_static_validator_path_compiles_for_llamafile(self):
        assert compile_unified_schema(SCHEMA, "llamafile") == compile_unified_schema(
            SCHEMA, "openai"
        )

    def test_a_llamafile_request_carries_the_wrapped_json_schema(self):
        compiled = _compile_schema_for_vendor(SCHEMA, "llamafile", "probe_reply")

        _invoke("llamafile", schema=compiled)

        response_format = _FakeOpenAI.requests[-1]["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["name"] == "probe_reply"
        assert response_format["json_schema"]["schema"]["required"] == ["answer"]


class TestVendorName:
    def test_the_expander_accepts_llamafile(self):
        validate_vendor_exists("llamafile", "classify_local")

    def test_the_expander_still_rejects_an_unknown_vendor(self):
        with pytest.raises(ConfigValidationError):
            validate_vendor_exists("llamafilez", "classify_local")
