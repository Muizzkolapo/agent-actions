"""The openai, anthropic and groq SDKs keep a 5 second connect limit under any request timeout."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.llm.config.endpoints import Endpoint
from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.anthropic.client import AnthropicClient
from agent_actions.llm.providers.groq.client import GroqClient
from agent_actions.llm.providers.openai.client import OpenAIClient
from agent_actions.llm.providers.openai.compatible import EndpointClient

ANSWER = '{"a": 1}'


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})
    with patch(
        "agent_actions.output.response.response_builder.ResponseBuilder.record_usage_and_event"
    ):
        yield


def _config(timeout: float | None, json_mode: bool = True) -> dict[str, Any]:
    config: dict[str, Any] = {"model_name": "m", "agent_type": "act", "json_mode": json_mode}
    if timeout is not None:
        config["request_timeout"] = timeout
    return config


def _call(client: Any, config: dict[str, Any]) -> None:
    if config["json_mode"]:
        client.call_json("k", config, "p", {"t": "x"}, None)
    else:
        client.call_non_json("k", config, "p", {"t": "x"})


def _chat_completion() -> MagicMock:
    return MagicMock(choices=[MagicMock(message=MagicMock(content=ANSWER))])


def _openai_family(path: str, client: Any, config: dict[str, Any]) -> Any:
    with patch(path) as sdk:
        sdk.return_value.chat.completions.create.return_value = _chat_completion()
        _call(client, config)
    return sdk.return_value.chat.completions.create.call_args.kwargs.get("timeout")


def _openai(config: dict[str, Any]) -> Any:
    return _openai_family("agent_actions.llm.providers.openai.client.OpenAI", OpenAIClient, config)


def _groq(config: dict[str, Any]) -> Any:
    return _openai_family("agent_actions.llm.providers.groq.client.Groq", GroqClient, config)


def _anthropic(config: dict[str, Any]) -> Any:
    with patch("anthropic.Anthropic") as sdk:
        block = SimpleNamespace(input={"a": 1}, text=ANSWER)
        sdk.return_value.messages.create.return_value = MagicMock(content=[block])
        _call(AnthropicClient, config)
    return sdk.return_value.messages.create.call_args.kwargs.get("timeout")


VENDORS = {"openai": _openai, "groq": _groq, "anthropic": _anthropic}


@pytest.mark.parametrize("json_mode", [True, False], ids=["json", "text"])
@pytest.mark.parametrize(("timeout", "read"), [(None, 600.0), (2.5, 2.5)], ids=["unset", "set"])
@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_the_request_timeout_reads_long_and_connects_short(vendor, timeout, read, json_mode):
    sent = VENDORS[vendor](_config(timeout, json_mode))

    assert isinstance(sent, httpx.Timeout)
    assert (sent.read, sent.write, sent.pool, sent.connect) == (read, read, read, 5.0)


def _endpoint_client() -> type[EndpointClient]:
    endpoint = Endpoint(name="corp", url="http://corp/v1", timeout_seconds=30.0)
    return type("CorpClient", (EndpointClient,), {"ENDPOINT": endpoint, "VENDOR": "corp"})


_OPENAI = "agent_actions.llm.providers.openai.client.OpenAI"


def test_a_declared_endpoint_keeps_the_connect_limit_on_a_set_timeout():
    sent = _openai_family(_OPENAI, _endpoint_client(), _config(2.5))

    assert (sent.read, sent.connect) == (2.5, 5.0)


def test_a_declared_endpoint_sends_no_per_request_timeout_when_unset():
    sent = _openai_family(_OPENAI, _endpoint_client(), _config(None))

    assert sent is None


@pytest.mark.parametrize("timeout", [None, 2.5], ids=["unset", "set"])
def test_a_declared_endpoint_refuses_text_mode_before_any_request(timeout):
    with patch(_OPENAI) as sdk, pytest.raises(ConfigValidationError, match="structured output"):
        _call(_endpoint_client(), _config(timeout, json_mode=False))

    assert sdk.return_value.chat.completions.create.call_args_list == []


class _OwnTimeout:
    """An SDK's own Timeout class, as one on httpx2 exports it; httpx's it refuses."""

    def __init__(self, read: float, *, connect: float):
        self.read, self.connect = read, connect


# vendor -> (the SDK module whose Timeout the request must use, run one request)
_OWN_SDK = {
    "anthropic": ("anthropic", _anthropic),
    "openai": ("openai", _openai),
    "groq": ("groq", _groq),
    "endpoint": ("openai", lambda config: _openai_family(_OPENAI, _endpoint_client(), config)),
}


@pytest.mark.parametrize("vendor", sorted(_OWN_SDK))
def test_the_timeout_is_built_with_the_sdks_own_class(vendor, monkeypatch):
    """Anthropic 1.x and OpenAI 3.x run on httpx2 and refuse an httpx.Timeout."""
    module, run = _OWN_SDK[vendor]
    monkeypatch.setattr(f"{module}.Timeout", _OwnTimeout)

    sent = run(_config(2.5))

    assert isinstance(sent, _OwnTimeout)
    assert (sent.read, sent.connect) == (2.5, 5.0)
