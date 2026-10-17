"""A transport failure from any provider SDK is a retriable `NetworkError`.

The ollama SDK turns `httpx.ConnectError` into a builtin `ConnectionError`; it and
the gemini and cohere SDKs let other httpx transport errors (a dropped read, a
connection closed mid-response) through untouched. The provider clients wrapped
none of them, so the retry service gave the record up on its first attempt.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from ollama import ChatResponse, Message

from agent_actions.errors import NetworkError
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.ollama.client import OllamaCloudClient, OllamaLocalClient
from agent_actions.processing.recovery.retry import RetryService, is_retriable_error

_REQUEST = httpx.Request("POST", "http://127.0.0.1:1/api/chat")

TRANSPORT_FAILURES = [
    ConnectionError("Failed to connect to Ollama."),
    ConnectionResetError("reset by peer"),
    TimeoutError("timed out"),
    httpx.ConnectError("refused", request=_REQUEST),
    httpx.ReadError("read failed", request=_REQUEST),
    httpx.WriteError("write failed", request=_REQUEST),
    httpx.RemoteProtocolError("closed mid-response", request=_REQUEST),
    httpx.ReadTimeout("read timed out", request=_REQUEST),
]

OLLAMA_CALLS = {
    "local_json": lambda: OllamaLocalClient.call_json(None, {"model_name": "m"}, "p", "c"),
    "local_text": lambda: OllamaLocalClient.call_non_json(None, {"model_name": "m"}, "p", "c"),
    "cloud_json": lambda: OllamaCloudClient.call_json("k", {"model_name": "m"}, "p", "c"),
    "cloud_text": lambda: OllamaCloudClient.call_non_json("k", {"model_name": "m"}, "p", "c"),
}


def _ids(failure: Exception) -> str:
    return type(failure).__name__


@pytest.mark.parametrize("failure", TRANSPORT_FAILURES, ids=_ids)
def test_any_vendor_mapping_wraps_a_transport_failure_as_network_error(failure):
    wrapped = wrap_vendor_error(failure, "m", VendorErrorMapping(vendor_name="any"))

    assert isinstance(wrapped, NetworkError)
    assert is_retriable_error(wrapped)


@pytest.mark.parametrize("failure", TRANSPORT_FAILURES, ids=_ids)
@pytest.mark.parametrize("call", sorted(OLLAMA_CALLS))
def test_an_ollama_transport_failure_is_retried_and_the_retry_answers(call, failure):
    answer = ChatResponse(model="m", message=Message(role="assistant", content='{"a": 1}'))
    with patch("ollama.Client.chat", side_effect=[failure, answer]) as chat:
        result = RetryService(max_attempts=2, base_delay=0).execute(OLLAMA_CALLS[call])

    assert chat.call_count == 2
    assert result.attempts == 2
    assert not result.exhausted
    assert result.response
