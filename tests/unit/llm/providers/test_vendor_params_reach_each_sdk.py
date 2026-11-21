"""An action's `vendor_params` reach every provider SDK's request.

Each SDK below is replaced by a mock that records what its request carried.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from ollama import ChatResponse, Message

from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.anthropic.client import AnthropicClient
from agent_actions.llm.providers.cohere.client import CohereClient
from agent_actions.llm.providers.gemini.client import GeminiClient
from agent_actions.llm.providers.groq.client import GroqClient
from agent_actions.llm.providers.ollama.client import OllamaCloudClient, OllamaLocalClient
from agent_actions.llm.providers.openai.client import OpenAIClient
from agent_actions.llm.providers.openai.compatible import PROFILE_CLIENTS

ANSWER = '{"a": 1}'


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})
    with patch(
        "agent_actions.output.response.response_builder.ResponseBuilder.record_usage_and_event"
    ):
        yield


def _config(vendor_params: dict[str, Any], json_mode: bool, **extra: Any) -> dict[str, Any]:
    return {
        "model_name": "m",
        "agent_type": "act",
        "json_mode": json_mode,
        "vendor_params": vendor_params,
        **extra,
    }


def _call(client: Any, api_key: str | None, config: dict[str, Any], schema: Any = None) -> Any:
    if config["json_mode"]:
        return client.call_json(api_key, config, "p", {"t": "x"}, schema)
    return client.call_non_json(api_key, config, "p", {"t": "x"})


def _openai_family(path: str, client: Any) -> Callable[..., dict[str, Any]]:
    def run(config: dict[str, Any]) -> dict[str, Any]:
        with patch(path) as sdk:
            sdk.return_value.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content=ANSWER))]
            )
            _call(client, "k", config)
        return sdk.return_value.chat.completions.create.call_args.kwargs

    return run


def _anthropic(config: dict[str, Any], schema: Any = None) -> dict[str, Any]:
    with patch("anthropic.Anthropic") as sdk:
        block = SimpleNamespace(input={"a": 1}, text=ANSWER)
        sdk.return_value.messages.create.return_value = MagicMock(content=[block])
        _call(AnthropicClient, "k", config, schema)
    return sdk.return_value.messages.create.call_args.kwargs


def _gemini(config: dict[str, Any]) -> dict[str, Any]:
    with patch("agent_actions.llm.providers.gemini.client._build_client") as build:
        build.return_value.models.generate_content.return_value = MagicMock(text=ANSWER)
        _call(GeminiClient, "k", config)
    request_config = build.return_value.models.generate_content.call_args.kwargs["config"]
    return request_config.model_dump(exclude_none=True)


def _cohere(config: dict[str, Any]) -> dict[str, Any]:
    with patch("cohere.ClientV2") as sdk:
        sdk.return_value.chat.return_value = MagicMock(
            message=MagicMock(content=[MagicMock(text=ANSWER)])
        )
        _call(CohereClient, "k", config)
    return sdk.return_value.chat.call_args.kwargs


def _ollama(client: Any, api_key: str | None) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def run(config: dict[str, Any]) -> dict[str, Any]:
        with patch("agent_actions.llm.providers.ollama.client.Client") as sdk:
            sdk.return_value.chat.return_value = ChatResponse(
                model="m", message=Message(role="assistant", content=ANSWER)
            )
            _call(client, api_key, config)
        return sdk.return_value.chat.call_args.kwargs

    return run


_OPENAI = "agent_actions.llm.providers.openai.client.OpenAI"

# vendor -> (run one request, vendor_params, what the request must carry)
VENDORS: dict[str, tuple[Callable[[dict[str, Any]], dict[str, Any]], dict, dict]] = {
    "openai": (
        _openai_family(_OPENAI, OpenAIClient),
        {"reasoning_effort": "low", "seed": 7},
        {"reasoning_effort": "low", "seed": 7},
    ),
    "llamafile": (
        _openai_family(_OPENAI, PROFILE_CLIENTS["llamafile"]),
        {"seed": 7},
        {"seed": 7},
    ),
    "groq": (
        _openai_family("agent_actions.llm.providers.groq.client.Groq", GroqClient),
        {"reasoning_format": "parsed"},
        {"reasoning_format": "parsed"},
    ),
    "anthropic": (
        _anthropic,
        {"thinking": {"type": "disabled"}, "top_k": 5},
        {"thinking": {"type": "disabled"}, "top_k": 5},
    ),
    "gemini": (
        _gemini,
        {"thinking_config": {"thinking_budget": 0}, "top_k": 5},
        {"thinking_config": {"thinking_budget": 0}, "top_k": 5},
    ),
    "cohere": (_cohere, {"k": 5, "seed": 7}, {"k": 5, "seed": 7}),
    "ollama_local": (
        _ollama(OllamaLocalClient, None),
        {"think": False, "keep_alive": "5m"},
        {"think": False, "keep_alive": "5m"},
    ),
    "ollama_cloud": (_ollama(OllamaCloudClient, "k"), {"think": True}, {"think": True}),
}


@pytest.mark.parametrize("json_mode", [True, False], ids=["json", "text"])
@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_vendor_params_reach_the_request(vendor, json_mode):
    run, vendor_params, expected = VENDORS[vendor]

    sent = run(_config(vendor_params, json_mode))

    assert {key: sent.get(key) for key in expected} == expected


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_no_vendor_params_leaves_the_request_as_it_was(vendor):
    run, vendor_params, _ = VENDORS[vendor]

    sent = run({**_config({}, json_mode=False)})

    assert not set(vendor_params) & set(sent)


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_a_vendor_param_replaces_the_value_agac_set(vendor):
    run, _, _ = VENDORS[vendor]
    temperature_key = "temperature"

    sent = run(_config({temperature_key: 0.9}, json_mode=False, temperature=0.1))

    assert sent[temperature_key] == 0.9


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_a_reserved_key_never_reaches_the_request(vendor):
    """Preflight refuses it; a config that skipped preflight still cannot change the model."""
    run, _, _ = VENDORS[vendor]

    sent = run(_config({"model": "other", "stream": True}, json_mode=False))

    assert sent.get("model") in ("m", None)
    assert sent.get("stream") in (False, None)


class TestOllamaOptions:
    def test_options_merge_into_the_generation_options(self):
        sent = _ollama(OllamaLocalClient, None)(
            _config({"options": {"num_ctx": 8192, "seed": 3}}, json_mode=True, max_tokens=256)
        )

        assert sent["options"] == {"num_predict": 256, "num_ctx": 8192, "seed": 3}

    def test_an_option_the_workflow_sets_wins(self):
        sent = _ollama(OllamaLocalClient, None)(
            _config({"options": {"num_predict": 512}}, json_mode=False, max_tokens=256)
        )

        assert sent["options"] == {"num_predict": 512}


class TestAnthropicExtraHeaders:
    def test_extra_headers_merge_with_the_caching_header(self):
        sent = _anthropic(
            _config(
                {"extra_headers": {"x-trace": "t1"}, "metadata": {"user_id": "u"}},
                json_mode=False,
                enable_prompt_caching=True,
            )
        )

        assert sent["extra_headers"] == {
            "anthropic-beta": "prompt-caching-2024-07-31",
            "x-trace": "t1",
        }
        assert sent["metadata"] == {"user_id": "u"}
