"""One model answer taken down the online path and down the batch path of each vendor.

Online, the vendor's client reads the SDK response and the passthrough transform builds
the record. In batch, the vendor's batch client reads the result line, the collect pass's
retrieval hands it over, and the batch result strategy builds the record. Both return
what the action stores under its own name, so a test can compare the two.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from ollama import ChatResponse, Message

from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.anthropic.client import AnthropicClient
from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient
from agent_actions.llm.providers.gemini.client import GeminiClient
from agent_actions.llm.providers.groq.batch_client import GroqBatchClient
from agent_actions.llm.providers.groq.client import GroqClient
from agent_actions.llm.providers.ollama.batch_client import OllamaBatchClient
from agent_actions.llm.providers.ollama.client import OllamaLocalClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.llm.providers.openai.client import OpenAIClient
from agent_actions.processing.helpers import _validate_llm_output_schema, transform_with_passthrough
from agent_actions.processing.types import ProcessingResult

ACTION = "tag_page"
GUID = "src-1"
ROW: dict[str, Any] = {
    "source_guid": GUID,
    "target_id": "r1",
    "content": {"source": {"page": "p1"}},
}
VENDORS = ("openai", "groq", "anthropic", "gemini", "ollama_local")
BATCH_ID = "b1"

USAGE = "agent_actions.output.response.response_builder.ResponseBuilder.record_usage_and_event"


def action_config(**settings: Any) -> dict[str, Any]:
    return {
        "action_name": ACTION,
        "agent_type": ACTION,
        "model_name": "m",
        "dependencies": ["upstream"],
        **settings,
    }


def without_the_reason(stored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The stored records, a parse error's wording aside."""
    return [
        {**record, "_parse_error": True} if "_parse_error" in record else record
        for record in stored
    ]


def _call(client: Any, config: dict[str, Any], schema: dict[str, Any] | None) -> list[Any]:
    key = None if client is OllamaLocalClient else "k"
    if config.get("json_mode", True):
        return client.call_json(key, config, "p", {"t": "x"}, schema)  # type: ignore[no-any-return]
    return client.call_non_json(key, config, "p", {"t": "x"})  # type: ignore[no-any-return]


def _openai_style(path: str, client: Any) -> Callable[..., list[Any]]:
    def run(text: str, config: dict[str, Any], schema: dict[str, Any] | None) -> list[Any]:
        with patch(path) as sdk:
            choice = MagicMock(finish_reason="stop")
            choice.message.content = text
            choice.message.refusal = None
            sdk.return_value.chat.completions.create.return_value = MagicMock(choices=[choice])
            return _call(client, config, schema)

    return run


def _anthropic(text: str, config: dict[str, Any], schema: dict[str, Any] | None) -> list[Any]:
    with patch("anthropic.Anthropic") as sdk:
        sdk.return_value.messages.create.return_value = MagicMock(
            content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn"
        )
        return _call(AnthropicClient, config, schema)


def _gemini(text: str, config: dict[str, Any], schema: dict[str, Any] | None) -> list[Any]:
    with patch("agent_actions.llm.providers.gemini.client._build_client") as build:
        build.return_value.models.generate_content.return_value = MagicMock(
            text=text, candidates=[MagicMock(finish_reason="STOP")]
        )
        return _call(GeminiClient, config, schema)


def _ollama(text: str, config: dict[str, Any], schema: dict[str, Any] | None) -> list[Any]:
    with patch("agent_actions.llm.providers.ollama.client.Client") as sdk:
        sdk.return_value.chat.return_value = ChatResponse(
            model="m", message=Message(role="assistant", content=text), done_reason="stop"
        )
        return _call(OllamaLocalClient, config, schema)


_ONLINE: dict[str, Callable[..., list[Any]]] = {
    "openai": _openai_style("agent_actions.llm.providers.openai.client.OpenAI", OpenAIClient),
    "groq": _openai_style("agent_actions.llm.providers.groq.client.Groq", GroqClient),
    "anthropic": _anthropic,
    "gemini": _gemini,
    "ollama_local": _ollama,
}


def online_answer(
    vendor: str, text: str, config: dict[str, Any], schema: dict[str, Any] | None = None
) -> list[Any]:
    """What the vendor's online client returns for a model that wrote *text*."""
    with patch(USAGE):
        answer = _ONLINE[vendor](text, config, schema)
    return _validate_llm_output_schema(answer, config, ACTION)  # type: ignore[no-any-return]


def online(
    vendor: str, text: str, config: dict[str, Any], schema: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """What the action stores under its name, online, for a model that wrote *text*."""
    records = transform_with_passthrough(
        online_answer(vendor, text, config, schema),
        {},
        GUID,
        config,
        action_name=ACTION,
        existing_content=ROW["content"],
        input_record=ROW,
    )
    return [record["content"][ACTION] for record in records]


def _openai_line(text: str) -> dict[str, Any]:
    return {
        "custom_id": "r1",
        "response": {
            "status_code": 200,
            "body": {
                "model": "m",
                "choices": [
                    {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        },
        "error": None,
    }


def _anthropic_line(text: str) -> dict[str, Any]:
    return {
        "custom_id": "r1",
        "result": {
            "type": "succeeded",
            "message": {
                "model": "m",
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        },
    }


def _gemini_line(text: str) -> dict[str, Any]:
    return {
        "key": "r1",
        "response": {
            "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
        },
    }


def _bare(cls: type, **attrs: Any) -> Any:
    client = cls.__new__(cls)
    for name, value in attrs.items():
        setattr(client, name, value)
    return client


def batch_client(vendor: str) -> Any:
    if vendor == "ollama_local":
        return OllamaBatchClient(base_url="http://localhost:11434")
    if vendor == "agac-provider":
        return AgacBatchClient()
    if vendor == "anthropic":
        return _bare(AnthropicBatchClient, enable_prompt_caching=False)
    return _bare(
        {"openai": OpenAIBatchClient, "groq": GroqBatchClient, "gemini": GeminiBatchClient}[vendor]
    )


def result_line(vendor: str, text: str) -> dict[str, Any]:
    """The line the vendor's batch returns for a model that wrote *text*."""
    if vendor == "anthropic":
        return _anthropic_line(text)
    if vendor == "gemini":
        return _gemini_line(text)
    return _openai_line(text)


def batch_result(
    vendor: str, text: str, config: dict[str, Any], output_directory: Path
) -> ProcessingResult:
    """The collect pass's result for a batch whose one line answers *text*."""
    provider = batch_client(vendor)
    raw = (json.dumps(result_line(vendor, text)) + "\n").encode("utf-8")
    if vendor == "ollama_local":
        # The Ollama client reads the file its own submit wrote.
        (output_directory / "batch").mkdir(parents=True, exist_ok=True)
        (output_directory / "batch" / f"{BATCH_ID}_results.jsonl").write_bytes(raw)
    else:
        provider._fetch_raw_results = lambda batch_id: raw
    context_map = {"r1": dict(ROW)}
    results = retrieve_and_reconcile(
        provider, BATCH_ID, str(output_directory), context_map=context_map, agent_config=config
    )
    (result,) = BatchResultStrategy().process(results, context_map=context_map, agent_config=config)
    return result


def batch(
    vendor: str, text: str, config: dict[str, Any], output_directory: Path
) -> list[dict[str, Any]]:
    """What the action stores under its name, in batch, for a model that wrote *text*."""
    result = batch_result(vendor, text, config, output_directory)
    return [record["content"][ACTION] for record in result.data]
