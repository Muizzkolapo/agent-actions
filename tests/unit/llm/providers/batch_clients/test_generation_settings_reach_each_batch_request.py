"""An action's top_p, stop and penalties reach each batch request line, as they reach an online one.

Batch built each task from model_name, temperature, max_tokens and vendor_params alone, so a
batch action ran with the vendor's defaults for the rest. Each line names a setting as the
vendor's online client does, and leaves out a setting the action does not set.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient
from agent_actions.llm.providers.groq.batch_client import GroqBatchClient
from agent_actions.llm.providers.ollama.batch_client import OllamaBatchClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient

ROW = {"target_id": "r1", "content": {"t": "x"}, "prompt": "p"}
SETTINGS = {"top_p": 0.9, "stop": "END", "frequency_penalty": 0.5, "presence_penalty": 0.25}


def _bare(cls: type, **attrs: Any) -> Any:
    client = cls.__new__(cls)
    for key, value in attrs.items():
        setattr(client, key, value)
    return client


def _line(client: Any, settings: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {"model_name": "m", "json_mode": False, **settings}
    (task,) = client.prepare_tasks([dict(ROW)], config)
    return task


@pytest.mark.parametrize("cls", [OpenAIBatchClient, GroqBatchClient], ids=["openai", "groq"])
def test_an_openai_shaped_body_carries_every_setting(cls):
    body = _line(_bare(cls), SETTINGS)["body"]

    assert {key: body.get(key) for key in SETTINGS} == SETTINGS


def test_anthropic_params_carry_top_p_and_stop_sequences():
    params = _line(_bare(AnthropicBatchClient, enable_prompt_caching=False), SETTINGS)["params"]

    assert (params["top_p"], params["stop_sequences"]) == (0.9, ["END"])
    assert "frequency_penalty" not in params
    assert "stop" not in params


def test_gemini_generation_config_carries_top_p_and_stop_sequences():
    config = _line(_bare(GeminiBatchClient), SETTINGS)["request"]["generation_config"]

    assert (config["top_p"], config["stop_sequences"]) == (0.9, ["END"])
    assert "frequency_penalty" not in config


def test_ollama_options_carry_top_p_and_stop():
    client = OllamaBatchClient(base_url="http://localhost:11434")
    client.client = MagicMock()
    client.client.chat.return_value = {
        "model": "m",
        "message": {"role": "assistant", "content": "ok"},
        "done": True,
    }

    client._process_single_task(_line(client, SETTINGS), 0, 1)

    options = client.client.chat.call_args.kwargs["options"]
    assert (options["top_p"], options["stop"]) == (0.9, ["END"])


@pytest.mark.parametrize(
    ("client", "where"),
    [
        (_bare(OpenAIBatchClient), ("body",)),
        (_bare(GroqBatchClient), ("body",)),
        (_bare(AnthropicBatchClient, enable_prompt_caching=False), ("params",)),
        (_bare(GeminiBatchClient), ("request",)),
        (OllamaBatchClient(base_url="http://localhost:11434"), ("body",)),
    ],
    ids=["openai", "groq", "anthropic", "gemini", "ollama"],
)
def test_an_unset_setting_is_left_out(client, where):
    line = _line(client, {key: None for key in SETTINGS})
    for key in where:
        line = line[key]
    sent = {**line, **line.get("generation_config", {})}

    assert not {"top_p", "stop", "stop_sequences", "frequency_penalty", "presence_penalty"} & set(
        sent
    )
