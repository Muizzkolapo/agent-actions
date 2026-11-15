"""An Anthropic batch request with an empty prompt sends no system prompt, with caching on or off."""

from __future__ import annotations

import json
from typing import Any

import pytest

from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver

CONTENT = {"page": "alpha"}
MARK = {"type": "ephemeral"}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "sk-ant-test")


def _params(caching: bool, prompt: str) -> dict[str, Any]:
    action = {
        "agent_type": "summarize",
        "model_vendor": "anthropic",
        "model_name": "claude-sonnet-4-6",
        "api_key": "TEST_ANTHROPIC_KEY",
        "enable_prompt_caching": caching,
    }
    client = BatchClientResolver().get_for_config(action)
    row = {"target_id": "r1", "content": CONTENT, "prompt": prompt}
    (task,) = client.prepare_tasks([row], {"model_name": "claude-sonnet-4-6"})
    return task["params"]


@pytest.mark.parametrize("caching", [True, False], ids=["caching-on", "caching-off"])
def test_an_empty_prompt_sends_no_system_prompt(caching):
    params = _params(caching, prompt="")

    assert "system" not in params
    (message,) = params["messages"]
    assert message["content"] == json.dumps(CONTENT)


def test_a_prompt_with_caching_on_is_sent_as_a_marked_system_prompt():
    params = _params(True, prompt="Summarise the page.")

    assert params["system"] == [
        {"type": "text", "text": "Summarise the page.", "cache_control": MARK}
    ]
