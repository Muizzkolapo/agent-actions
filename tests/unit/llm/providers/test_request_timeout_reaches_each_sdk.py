"""An action's `request_timeout` reaches every provider SDK as its per-request timeout.

Unset, nothing is passed, so each SDK keeps the timeout it has always had. Each SDK
below is replaced by a mock that records what it was built and called with.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from ollama import ChatResponse, Message

from agent_actions.llm.config.endpoints import Endpoint
from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.anthropic.client import AnthropicClient
from agent_actions.llm.providers.cohere.client import CohereClient
from agent_actions.llm.providers.gemini.client import GeminiClient
from agent_actions.llm.providers.groq.client import GroqClient
from agent_actions.llm.providers.ollama.client import OllamaCloudClient, OllamaLocalClient
from agent_actions.llm.providers.openai.client import OpenAIClient
from agent_actions.llm.providers.openai.compatible import PROFILE_CLIENTS, EndpointClient

ANSWER = '{"a": 1}'


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})
    with patch(
        "agent_actions.output.response.response_builder.ResponseBuilder.record_usage_and_event"
    ):
        yield


def _config(timeout: float | None, json_mode: bool) -> dict[str, Any]:
    config: dict[str, Any] = {"model_name": "m", "agent_type": "act", "json_mode": json_mode}
    if timeout is not None:
        config["request_timeout"] = timeout
    return config


def _call(client: Any, api_key: str | None, config: dict[str, Any]) -> list[dict[str, Any]]:
    if config["json_mode"]:
        return client.call_json(api_key, config, "p", {"t": "x"}, None)
    return client.call_non_json(api_key, config, "p", {"t": "x"})


def _chat_completion() -> MagicMock:
    return MagicMock(choices=[MagicMock(message=MagicMock(content=ANSWER))])


class _Sent:
    """What one SDK was built with and what its request carried."""

    def __init__(self, built: dict[str, Any], called: dict[str, Any]):
        self.built = built
        self.called = called


def _openai_family(path: str, client: Any) -> Callable[[dict[str, Any]], _Sent]:
    def run(config: dict[str, Any]) -> _Sent:
        with patch(path) as sdk:
            sdk.return_value.chat.completions.create.return_value = _chat_completion()
            _call(client, "k", config)
        return _Sent(
            sdk.call_args.kwargs, sdk.return_value.chat.completions.create.call_args.kwargs
        )

    return run


def _anthropic(config: dict[str, Any]) -> _Sent:
    with patch("anthropic.Anthropic") as sdk:
        block = SimpleNamespace(input={"a": 1}, text=ANSWER)
        sdk.return_value.messages.create.return_value = MagicMock(content=[block])
        _call(AnthropicClient, "k", config)
    return _Sent(sdk.call_args.kwargs, sdk.return_value.messages.create.call_args.kwargs)


def _gemini(config: dict[str, Any]) -> _Sent:
    with patch("agent_actions.llm.providers.gemini.client._build_client") as build:
        build.return_value.models.generate_content.return_value = MagicMock(text=ANSWER)
        _call(GeminiClient, "k", config)
    called = build.return_value.models.generate_content.call_args.kwargs
    options = getattr(called["config"], "http_options", None)
    # As the SDK takes it: whole milliseconds.
    return _Sent({}, {"timeout": options.timeout} if options is not None else {})


def _cohere(config: dict[str, Any]) -> _Sent:
    with patch("cohere.ClientV2") as sdk:
        sdk.return_value.chat.return_value = MagicMock(
            message=MagicMock(content=[MagicMock(text=ANSWER)])
        )
        _call(CohereClient, "k", config)
    return _Sent(sdk.call_args.kwargs, sdk.return_value.chat.call_args.kwargs)


def _ollama(client: Any, api_key: str | None) -> Callable[[dict[str, Any]], _Sent]:
    def run(config: dict[str, Any]) -> _Sent:
        with patch("agent_actions.llm.providers.ollama.client.Client") as sdk:
            sdk.return_value.chat.return_value = ChatResponse(
                model="m", message=Message(role="assistant", content=ANSWER)
            )
            _call(client, api_key, config)
        return _Sent(sdk.call_args.kwargs, sdk.return_value.chat.call_args.kwargs)

    return run


_OPENAI = "agent_actions.llm.providers.openai.client.OpenAI"

# vendor -> (run one request, where the timeout goes, the value the SDK takes for 2.5s)
VENDORS: dict[str, tuple[Callable[[dict[str, Any]], _Sent], str, float]] = {
    "openai": (_openai_family(_OPENAI, OpenAIClient), "called", 2.5),
    "llamafile": (_openai_family(_OPENAI, PROFILE_CLIENTS["llamafile"]), "called", 2.5),
    "groq": (
        _openai_family("agent_actions.llm.providers.groq.client.Groq", GroqClient),
        "called",
        2.5,
    ),
    "anthropic": (_anthropic, "called", 2.5),
    "gemini": (_gemini, "called", 2500),
    "cohere": (_cohere, "built", 2.5),
    "ollama_local": (_ollama(OllamaLocalClient, None), "built", 2.5),
    "ollama_cloud": (_ollama(OllamaCloudClient, "k"), "built", 2.5),
}


@pytest.mark.parametrize("json_mode", [True, False], ids=["json", "text"])
@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_a_set_request_timeout_reaches_the_sdk(vendor, json_mode):
    run, where, expected = VENDORS[vendor]

    sent = run(_config(2.5, json_mode))

    assert getattr(sent, where)["timeout"] == expected


@pytest.mark.parametrize("json_mode", [True, False], ids=["json", "text"])
@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_an_unset_request_timeout_passes_nothing(vendor, json_mode):
    run, _, _ = VENDORS[vendor]

    sent = run(_config(None, json_mode))

    assert "timeout" not in sent.built
    assert "timeout" not in sent.called


def _endpoint_client(timeout_seconds: float) -> type[EndpointClient]:
    endpoint = Endpoint(name="corp", url="http://corp/v1", timeout_seconds=timeout_seconds)
    return type("CorpClient", (EndpointClient,), {"ENDPOINT": endpoint, "VENDOR": "corp"})


class TestADeclaredEndpoint:
    """The endpoint's timeout_seconds builds the client; request_timeout is per request."""

    def test_request_timeout_wins_over_the_endpoint_timeout(self):
        run = _openai_family(_OPENAI, _endpoint_client(30.0))

        sent = run(_config(2.5, json_mode=True))

        assert sent.built["timeout"] == 30.0
        assert sent.called["timeout"] == 2.5

    def test_unset_the_endpoint_timeout_stands(self):
        run = _openai_family(_OPENAI, _endpoint_client(30.0))

        sent = run(_config(None, json_mode=True))

        assert sent.built["timeout"] == 30.0
        assert "timeout" not in sent.called
