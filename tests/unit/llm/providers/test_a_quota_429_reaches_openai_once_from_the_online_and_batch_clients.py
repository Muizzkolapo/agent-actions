"""A 429 that says the quota is used up reaches OpenAI once from the clients agac builds.

The SDK sends a 429 again, twice by default. Each test builds the client the way a run
does, with only the wire swapped for a local transport, and counts the requests sent.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import openai
import pytest

from agent_actions.errors import QuotaExceededError
from agent_actions.llm.providers.openai import batch_client as batch_module
from agent_actions.llm.providers.openai import client as online_module
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.llm.providers.openai.client import OpenAIClient
from tests.unit.llm.providers.test_a_quota_or_billing_answer_is_not_a_rate_limit import (
    OPENAI_QUOTA,
)


def _sdk_on_a_wire_that_answers_quota(sent: list[httpx.Request]) -> type[openai.OpenAI]:
    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(429, json=OPENAI_QUOTA)

    class OpenAIOnTheWire(openai.OpenAI):
        def __init__(self, **kwargs):
            super().__init__(
                http_client=httpx.Client(transport=httpx.MockTransport(answer)), **kwargs
            )

    return OpenAIOnTheWire


@pytest.mark.parametrize(
    "call",
    [
        lambda config: OpenAIClient.call_json("k", config, "Say hi", {}, None),
        lambda config: OpenAIClient.call_non_json("k", config, "Say hi", {}),
    ],
    ids=["call_json", "call_non_json"],
)
def test_the_online_client_sends_a_quota_429_once(call):
    sent: list[httpx.Request] = []

    with (
        patch.object(online_module, "OpenAI", _sdk_on_a_wire_that_answers_quota(sent)),
        patch.object(openai._base_client.time, "sleep"),
        pytest.raises(QuotaExceededError),
    ):
        call({"model_name": "gpt-4o-mini"})

    assert len(sent) == 1


def test_the_batch_client_sends_a_quota_429_once(tmp_path):
    sent: list[httpx.Request] = []
    batch_input = tmp_path / "batch.jsonl"
    batch_input.write_text("{}\n")

    with patch.object(batch_module, "OpenAI", _sdk_on_a_wire_that_answers_quota(sent)):
        client = OpenAIBatchClient(api_key="k")
    with (
        patch.object(openai._base_client.time, "sleep"),
        pytest.raises(openai.RateLimitError),
    ):
        client._submit_to_provider_api(batch_input, "batch")

    assert len(sent) == 1
