"""An Anthropic batch request sends its prompt in the user message, as online does, never as a
system prompt."""

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


def _text(content: str | list[dict[str, Any]]) -> str:
    return content if isinstance(content, str) else "".join(block["text"] for block in content)


@pytest.mark.parametrize("caching", [True, False], ids=["caching-on", "caching-off"])
def test_an_empty_prompt_sends_no_system_prompt(caching):
    params = _params(caching, prompt="")

    assert "system" not in params
    (message,) = params["messages"]
    assert _text(message["content"]) == (
        "\n<|begin_of_user_instruction|>:  :<|end_of_user_instruction|>\n"
        f"<|begin_of_text|>: {json.dumps(CONTENT)} :<|end_of_text|>\n"
    )


def test_a_prompt_with_caching_on_is_marked_in_the_user_message():
    params = _params(True, prompt="Summarise the page.")

    assert "system" not in params
    (message,) = params["messages"]
    marked, record = message["content"]
    assert marked == {
        "type": "text",
        "text": "\n<|begin_of_user_instruction|>: Summarise the page.",
        "cache_control": MARK,
    }
    assert "cache_control" not in record
    assert json.dumps(CONTENT) in record["text"]
