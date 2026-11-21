"""A batch request carries a temperature only when the action sets one, as an online call does.

The base client fell back to 0.1 for a config without the key, and the mock provider's task
wrote the unset value as null.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient
from agent_actions.llm.providers.groq.batch_client import GroqBatchClient
from agent_actions.llm.providers.ollama.batch_client import OllamaBatchClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient

ROW = {"target_id": "r1", "content": {"t": "x"}, "prompt": "p"}
UNSET: dict[str, dict[str, Any]] = {"no key": {}, "null": {"temperature": None}}


def _bare(cls: type, **attrs: Any) -> Any:
    client = cls.__new__(cls)
    for key, value in attrs.items():
        setattr(client, key, value)
    return client


CLIENTS = {
    "openai": lambda: _bare(OpenAIBatchClient),
    "groq": lambda: _bare(GroqBatchClient),
    "anthropic": lambda: _bare(AnthropicBatchClient, enable_prompt_caching=False),
    "gemini": lambda: _bare(GeminiBatchClient),
    "ollama": lambda: OllamaBatchClient(base_url="http://localhost:11434"),
    "agac-provider": lambda: _bare(AgacBatchClient),
}


def _task(vendor: str, settings: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {"model_name": "m", "json_mode": False, **settings}
    (task,) = CLIENTS[vendor]().prepare_tasks([dict(ROW)], config)
    return task


def _temperatures(value: Any) -> list[Any]:
    """Every value stored under a `temperature` key, at any depth."""
    if isinstance(value, dict):
        found = [v for k, v in value.items() if k == "temperature"]
        return found + [t for v in value.values() for t in _temperatures(v)]
    if isinstance(value, list):
        return [t for v in value for t in _temperatures(v)]
    return []


@pytest.mark.parametrize("vendor", CLIENTS)
@pytest.mark.parametrize("settings", UNSET.values(), ids=UNSET.keys())
def test_an_unset_temperature_is_left_out_of_the_request(vendor, settings):
    assert _temperatures(_task(vendor, settings)) == []


@pytest.mark.parametrize("vendor", CLIENTS)
def test_a_set_temperature_is_sent(vendor):
    assert _temperatures(_task(vendor, {"temperature": 0.4})) == [0.4]
