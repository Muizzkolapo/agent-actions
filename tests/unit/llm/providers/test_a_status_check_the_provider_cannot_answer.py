"""A batch status check the provider cannot answer now raises ConnectionError.

Its callers take that as "ask again on the next run". Each SDK raises its own connection
and server errors, none of them an OSError, so a provider out of reach was taken for any
other error and failed the action.
"""

from __future__ import annotations

import anthropic
import groq
import httpx
import openai
import pytest
from google.genai import errors as genai_errors

from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient
from agent_actions.llm.providers.groq.batch_client import GroqBatchClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient

_REQUEST = httpx.Request("GET", "https://provider.test/batches/batch-1")


def _response(code: int) -> httpx.Response:
    return httpx.Response(code, request=_REQUEST)


def _gemini(code: int) -> dict:
    return {"error": {"code": code, "message": "", "status": ""}}


UNANSWERED = [
    pytest.param(OpenAIBatchClient, openai.APIConnectionError(request=_REQUEST), id="openai"),
    pytest.param(OpenAIBatchClient, openai.APITimeoutError(request=_REQUEST), id="openai-timeout"),
    pytest.param(
        OpenAIBatchClient,
        openai.InternalServerError("", response=_response(500), body=None),
        id="openai-500",
    ),
    pytest.param(
        AnthropicBatchClient, anthropic.APIConnectionError(request=_REQUEST), id="anthropic"
    ),
    pytest.param(
        AnthropicBatchClient,
        anthropic.InternalServerError("", response=_response(529), body=None),
        id="anthropic-529",
    ),
    pytest.param(GroqBatchClient, groq.APIConnectionError(request=_REQUEST), id="groq"),
    pytest.param(
        GroqBatchClient,
        groq.InternalServerError("", response=_response(503), body=None),
        id="groq-503",
    ),
    pytest.param(GeminiBatchClient, httpx.ConnectError("refused", request=_REQUEST), id="gemini"),
    pytest.param(GeminiBatchClient, genai_errors.ServerError(503, _gemini(503)), id="gemini-503"),
]

ANSWERED = [
    pytest.param(
        OpenAIBatchClient,
        openai.NotFoundError("", response=_response(404), body=None),
        id="openai",
    ),
    pytest.param(
        AnthropicBatchClient,
        anthropic.NotFoundError("", response=_response(404), body=None),
        id="anthropic",
    ),
    pytest.param(
        GroqBatchClient, groq.NotFoundError("", response=_response(404), body=None), id="groq"
    ),
    pytest.param(GeminiBatchClient, genai_errors.ClientError(404, _gemini(404)), id="gemini"),
]


def _client(client_type, error: Exception):
    client = client_type(api_key="test")

    def fetch_status(batch_id: str) -> str:
        raise error

    client._fetch_status = fetch_status
    return client


@pytest.mark.parametrize(("client_type", "error"), UNANSWERED)
def test_a_provider_that_cannot_answer_now_raises_connection_error(client_type, error):
    with pytest.raises(ConnectionError) as raised:
        _client(client_type, error).check_status("batch-1")

    assert raised.value.__cause__ is error


@pytest.mark.parametrize(("client_type", "error"), ANSWERED)
def test_a_provider_that_does_not_know_the_batch_is_not_taken_as_out_of_reach(client_type, error):
    """That is an answer, the same on every run: waited for, it would hold the action."""
    with pytest.raises(type(error)):
        _client(client_type, error).check_status("batch-1")
