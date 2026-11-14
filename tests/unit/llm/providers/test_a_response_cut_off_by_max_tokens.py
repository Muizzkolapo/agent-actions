"""A response the output budget cut off before any answer names its stop reason, and retries.

A model that thinks first can spend the whole budget thinking. The record used to fail
at its first attempt with "Empty response content from Anthropic API", which did not say
why, and the error was not retriable.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from ollama import ChatResponse, Message

from agent_actions.errors import ResponseTruncatedError, VendorAPIError
from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.anthropic.client import AnthropicClient
from agent_actions.llm.providers.cohere.client import CohereClient
from agent_actions.llm.providers.gemini.client import GeminiClient
from agent_actions.llm.providers.groq.client import GroqClient
from agent_actions.llm.providers.ollama.client import OllamaLocalClient
from agent_actions.llm.providers.openai.client import OpenAIClient
from agent_actions.processing.recovery.retry import classify_error, is_retriable_error

CONFIG = {"model_name": "m", "agent_type": "act"}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})
    with patch(
        "agent_actions.output.response.response_builder.ResponseBuilder.record_usage_and_event"
    ):
        yield


def _anthropic(stop_reason: str) -> Any:
    with patch("anthropic.Anthropic") as sdk:
        thinking_only = SimpleNamespace(thinking="...")
        sdk.return_value.messages.create.return_value = MagicMock(
            content=[thinking_only], stop_reason=stop_reason
        )
        return AnthropicClient.call_non_json("k", CONFIG, "p", {"t": "x"})


def _openai_style(path: str, client: Any, finish_reason: str) -> Any:
    with patch(path) as sdk:
        choice = MagicMock(finish_reason=finish_reason)
        choice.message.content = None
        sdk.return_value.chat.completions.create.return_value = MagicMock(choices=[choice])
        return client.call_non_json("k", CONFIG, "p", {"t": "x"})


def _gemini(finish_reason: Any) -> Any:
    with patch("agent_actions.llm.providers.gemini.client._build_client") as build:
        build.return_value.models.generate_content.return_value = MagicMock(
            text=None, candidates=[MagicMock(finish_reason=finish_reason)]
        )
        return GeminiClient.call_non_json("k", CONFIG, "p", {"t": "x"})


def _cohere(finish_reason: str) -> Any:
    with patch("cohere.ClientV2") as sdk:
        sdk.return_value.chat.return_value = MagicMock(
            message=MagicMock(content=[]), finish_reason=finish_reason
        )
        return CohereClient.call_non_json("k", CONFIG, "p", {"t": "x"})


def _ollama(done_reason: str) -> Any:
    with patch("agent_actions.llm.providers.ollama.client.Client") as sdk:
        sdk.return_value.chat.return_value = ChatResponse(
            model="m", message=Message(role="assistant", content=""), done_reason=done_reason
        )
        return OllamaLocalClient.call_non_json(None, CONFIG, "p", {"t": "x"})


def _gemini_max_tokens() -> Any:
    from google.genai import types

    return _gemini(types.FinishReason.MAX_TOKENS)


CUT_OFF = {
    "anthropic": (lambda: _anthropic("max_tokens"), "max_tokens"),
    "openai": (
        lambda: _openai_style(
            "agent_actions.llm.providers.openai.client.OpenAI", OpenAIClient, "length"
        ),
        "length",
    ),
    "groq": (
        lambda: _openai_style("agent_actions.llm.providers.groq.client.Groq", GroqClient, "length"),
        "length",
    ),
    "gemini": (_gemini_max_tokens, "MAX_TOKENS"),
    "cohere": (lambda: _cohere("MAX_TOKENS"), "MAX_TOKENS"),
    "ollama_local": (lambda: _ollama("length"), "length"),
}


@pytest.mark.parametrize("vendor", sorted(CUT_OFF))
def test_a_cut_off_response_is_a_retriable_error_naming_the_stop_reason(vendor):
    run, reason = CUT_OFF[vendor]

    with pytest.raises(ResponseTruncatedError) as caught:
        run()

    assert f"(stop_reason={reason})" in str(caught.value)
    assert "raise max_tokens" in str(caught.value)
    assert is_retriable_error(caught.value)
    assert classify_error(caught.value) == "truncated"


def test_another_empty_anthropic_response_names_its_stop_reason_and_is_not_retried():
    with pytest.raises(VendorAPIError) as caught:
        _anthropic("refusal")

    assert not isinstance(caught.value, ResponseTruncatedError)
    assert str(caught.value) == "Empty response content from Anthropic API (stop_reason=refusal)"
    assert not is_retriable_error(caught.value)


def test_another_empty_openai_response_names_its_stop_reason():
    with pytest.raises(VendorAPIError, match=r"\(stop_reason=content_filter\)") as caught:
        _openai_style(
            "agent_actions.llm.providers.openai.client.OpenAI", OpenAIClient, "content_filter"
        )

    assert not isinstance(caught.value, ResponseTruncatedError)


@pytest.mark.parametrize(
    "run",
    [lambda: _gemini("STOP"), lambda: _ollama("stop")],
    ids=["gemini", "ollama_local"],
)
def test_an_empty_answer_that_was_not_cut_off_is_left_to_on_empty(run):
    """These clients pass an empty answer on; only a cut-off one is an error."""
    run()


def test_a_json_answer_cut_off_by_anthropic_stays_a_parse_error_for_repair():
    with patch("anthropic.Anthropic") as sdk:
        sdk.return_value.messages.create.return_value = MagicMock(
            content=[SimpleNamespace(thinking="...")], stop_reason="max_tokens"
        )
        (result,) = AnthropicClient.call_json("k", CONFIG, "p", {"t": "x"}, None)

    assert "stop_reason=max_tokens" in result["_parse_error"]
