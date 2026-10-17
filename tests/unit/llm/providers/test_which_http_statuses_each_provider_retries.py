"""Which HTTP statuses each provider retries, as the retry reference's provider table says.

Each provider's own SDK answers a request with the status, and the provider's error
mapping wraps what it raises. A change here must change
docs.agent-actions/docs/reference/execution/retry.md with it.
"""

from __future__ import annotations

from collections.abc import Callable

import anthropic
import cohere
import groq
import httpx
import ollama
import openai
import pytest
from google import genai
from google.genai import types as genai_types

from agent_actions.llm.providers.anthropic.client import _ERROR_MAPPING as ANTHROPIC
from agent_actions.llm.providers.cohere.client import _ERROR_MAPPING as COHERE
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.gemini.client import _ERROR_MAPPING as GEMINI
from agent_actions.llm.providers.groq.client import _ERROR_MAPPING as GROQ
from agent_actions.llm.providers.ollama.client import _ERROR_MAPPING_LOCAL as OLLAMA
from agent_actions.llm.providers.ollama.client import _OLLAMA_ERRORS
from agent_actions.llm.providers.openai.client import _ERROR_MAPPING as OPENAI
from agent_actions.processing.recovery.retry import is_retriable_error

MESSAGES = [{"role": "user", "content": "hi"}]


def _answering(status: int) -> httpx.MockTransport:
    body = {"error": {"message": "boom", "code": status, "status": "X"}, "message": "boom"}
    return httpx.MockTransport(lambda _: httpx.Response(status, json=body))


def _http(status: int) -> httpx.Client:
    return httpx.Client(transport=_answering(status))


def _openai(status: int) -> None:
    client = openai.OpenAI(api_key="k", max_retries=0, http_client=_http(status))
    client.chat.completions.create(model="m", messages=MESSAGES)


def _anthropic(status: int) -> None:
    client = anthropic.Anthropic(api_key="k", max_retries=0, http_client=_http(status))
    client.messages.create(model="m", max_tokens=5, messages=MESSAGES)


def _groq(status: int) -> None:
    client = groq.Groq(api_key="k", max_retries=0, http_client=_http(status))
    client.chat.completions.create(model="m", messages=MESSAGES)


def _gemini(status: int) -> None:
    options = genai_types.HttpOptions(
        httpx_client=_http(status), retry_options=genai_types.HttpRetryOptions(attempts=1)
    )
    genai.Client(api_key="k", http_options=options).models.generate_content(
        model="m", contents="hi"
    )


def _cohere(status: int) -> None:
    cohere.ClientV2(api_key="k", httpx_client=_http(status)).chat(model="m", messages=MESSAGES)


def _ollama(status: int) -> None:
    client = ollama.Client(host="http://ollama", transport=_answering(status))
    client.chat(model="m", messages=MESSAGES)


PROVIDERS: dict[str, tuple[Callable[[int], None], VendorErrorMapping]] = {
    "openai": (_openai, OPENAI),
    "anthropic": (_anthropic, ANTHROPIC),
    "groq": (_groq, GROQ),
    "gemini": (_gemini, GEMINI),
    "cohere": (_cohere, COHERE),
    "ollama": (_ollama, OLLAMA),
}

ANY_5XX = {500, 501, 502, 503, 504, 505, 529}
RETRIED = {
    "openai": {429} | ANY_5XX,
    "groq": {429} | ANY_5XX,
    "anthropic": {429} | ANY_5XX - {529},
    "gemini": {429, 500, 502, 503, 504},
    "cohere": {429, 500, 502, 503, 504},
    "ollama": set(),
}


@pytest.mark.parametrize("status", sorted({429} | ANY_5XX))
@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_a_status_is_retried_only_where_the_retry_reference_says(provider, status):
    call, mapping = PROVIDERS[provider]
    catch = _OLLAMA_ERRORS if provider == "ollama" else Exception

    with pytest.raises(catch) as raised:
        call(status)
    wrapped = wrap_vendor_error(raised.value, "m", mapping, "r")

    assert is_retriable_error(wrapped) is (status in RETRIED[provider])
