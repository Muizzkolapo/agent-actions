"""A batch line asks the model what the online request asks, for the same prompt and record.

Online, the real SDK sends the request to a transport that records it. In batch, the
client's ``prepare_tasks`` builds the line. Both start from the action's config, the
rendered prompt and the record's context, as ``create_dynamic_agent`` and the batch
preparator hand them over.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import ollama
import pytest
from google import genai
from google.genai import types as genai_types

from agent_actions.errors import PromptTooLargeError
from agent_actions.expectations.judge import judge_call
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.services.side_batch import submit_side_batch
from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient
from agent_actions.llm.providers.groq.batch_client import GroqBatchClient
from agent_actions.llm.providers.ollama.batch_client import OllamaBatchClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.llm.realtime.builder import create_dynamic_agent
from agent_actions.llm.side_calls import OnlineSideCalls
from agent_actions.processing.helpers import run_dynamic_agent
from tests._support.sdk_http import http_library

VENDORS = ("anthropic", "gemini", "groq", "ollama_cloud", "ollama_local", "openai")
MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-2.5-flash",
    "groq": "llama-3.3-70b-versatile",
    "ollama_cloud": "llama3",
    "ollama_local": "llama3",
    "openai": "gpt-4o-mini",
}
PROMPT = "Summarise the document."
RECORD = {"doc": {"title": "Café ☕", "n": [1, {"x": 2}], "score": float("nan")}}
# The record as the model must read it: JSON as written, the NaN as null.
RECORD_TEXT = '{"doc": {"title": "Café ☕", "n": [1, {"x": 2}], "score": null}}'
SCHEMA = {"summary": "string", "tags": "array[string]"}
ANSWER = '{"summary": "s", "tags": []}'
FEEDBACK = "Your previous output failed: the summary is empty."
MARK = {"type": "ephemeral"}

_REPLIES: dict[str, dict[str, Any]] = {
    "anthropic": {
        "id": "m",
        "type": "message",
        "role": "assistant",
        "model": "m",
        "content": [{"type": "text", "text": ANSWER}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    },
    "chat": {
        "id": "c",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": ANSWER},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    },
    "gemini": {
        "candidates": [
            {"content": {"parts": [{"text": ANSWER}], "role": "model"}, "finishReason": "STOP"}
        ],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
    },
    "ollama": {
        "model": "m",
        "created_at": "2026-01-01T00:00:00Z",
        "message": {"role": "assistant", "content": ANSWER},
        "done": True,
        "done_reason": "stop",
    },
}


def _config(vendor: str, *, json_mode: bool, schema: bool, **extra: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "agent_type": "summarize",
        "action_name": "summarize",
        "name": "summarize",
        "model_vendor": vendor,
        "model_name": MODELS[vendor],
        "api_key": "TEST_PROVIDER_KEY",
        "json_mode": json_mode,
        "granularity": "record",
        "prompt": PROMPT,
        "context_scope": {"observe": ["source.doc"]},
        **extra,
    }
    if schema:
        config["schema"] = SCHEMA
    return config


@contextmanager
def _online_wire(vendor: str) -> Iterator[list[dict[str, Any]]]:
    """Every request body the vendor's real SDK sends while the block runs."""
    sent: list[dict[str, Any]] = []

    def responder(http: Any, reply: dict[str, Any]) -> Callable[[Any], Any]:
        def handler(request: Any) -> Any:
            sent.append(json.loads(request.content))
            return http.Response(200, json=reply)

        return handler

    if vendor in ("anthropic", "groq", "openai"):
        http = http_library(importlib.import_module(vendor))
        handler = responder(http, _REPLIES["anthropic" if vendor == "anthropic" else "chat"])

        def sdk_client(cls: type, api_key: str | None, **kwargs: Any) -> Any:
            transport = http.MockTransport(handler)
            return cls(
                api_key=api_key,
                max_retries=0,
                http_client=http.Client(transport=transport),
                **kwargs,
            )

        patcher = patch.object(client_base, "get_or_create_client", sdk_client)
    elif vendor == "gemini":
        handler = responder(httpx, _REPLIES["gemini"])

        def gemini_client(api_key: str) -> Any:
            return genai.Client(
                api_key=api_key,
                http_options=genai_types.HttpOptions(
                    httpx_client=httpx.Client(transport=httpx.MockTransport(handler))
                ),
            )

        patcher = patch("agent_actions.llm.providers.gemini.client._build_client", gemini_client)
    else:
        handler = responder(httpx, _REPLIES["ollama"])

        def ollama_client(**kwargs: Any) -> Any:
            return ollama.Client(transport=httpx.MockTransport(handler), **kwargs)

        patcher = patch("agent_actions.llm.providers.ollama.client.Client", ollama_client)
    with patcher:
        yield sent


def _batch_client(vendor: str, *, caching: bool = False) -> Any:
    if vendor == "anthropic":
        return AnthropicBatchClient(api_key="k", enable_prompt_caching=caching)
    if vendor == "gemini":
        return GeminiBatchClient(api_key="k")
    if vendor == "groq":
        return GroqBatchClient(api_key="k")
    if vendor == "openai":
        return OpenAIBatchClient(api_key="k")
    cloud = vendor == "ollama_cloud"
    return OllamaBatchClient(vendor_slug=vendor, cloud=cloud, api_key="k" if cloud else None)


def _asked(vendor: str, request: dict[str, Any]) -> dict[str, Any]:
    """What a request body, online's or a batch line's, gives the model to read."""
    if vendor == "gemini":
        system = request.get("systemInstruction", request.get("system_instruction"))
        texts = [part["text"] for content in request["contents"] for part in content["parts"]]
        return {"texts": texts, "system": system}
    messages = request["messages"]
    if vendor.startswith("ollama"):
        # The Ollama SDK sends an empty content as no content, from either mode.
        messages = [{k: v for k, v in message.items() if v != ""} for message in messages]
    return {"messages": messages, "system": request.get("system")}


def _batch_request(vendor: str, task: dict[str, Any]) -> dict[str, Any]:
    if vendor == "gemini":
        return task["request"]
    return task["params"] if vendor == "anthropic" else task["body"]


def _text(asked: dict[str, Any]) -> str:
    def walk(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return "".join(walk(item) for key, item in value.items() if key != "role")
        if isinstance(value, list):
            return "".join(walk(item) for item in value)
        return ""

    return walk(asked)


def _online(config: dict[str, Any], record: Any = RECORD, prompt: str = PROMPT) -> dict[str, Any]:
    vendor = config["model_vendor"]
    with _online_wire(vendor) as sent:
        create_dynamic_agent(config, record, prompt)
    (body,) = sent
    return _asked(vendor, body)


def _batch(config: dict[str, Any], record: Any = RECORD, prompt: str = PROMPT) -> dict[str, Any]:
    vendor = config["model_vendor"]
    client = _batch_client(vendor)
    # The schema as the batch preparator compiles it and hands it over.
    compiled = BatchTaskPreparator()._prepare_schema(config, client, None)
    (task,) = client.prepare_tasks(
        [{"target_id": "r1", "content": record, "prompt": prompt}],
        {**config, "compiled_schema": compiled},
    )
    return _asked(vendor, _batch_request(vendor, task))


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "k")


@pytest.mark.parametrize("schema", [True, False], ids=["schema", "no-schema"])
@pytest.mark.parametrize("json_mode", [True, False], ids=["json", "text"])
@pytest.mark.parametrize("vendor", VENDORS)
class TestTheSameRequest:
    def test_the_batch_line_carries_the_online_request(self, vendor, json_mode, schema):
        config = _config(vendor, json_mode=json_mode, schema=schema)

        assert _batch(config) == _online(config)

    def test_the_record_goes_out_as_the_json_it_is(self, vendor, json_mode, schema):
        config = _config(vendor, json_mode=json_mode, schema=schema)

        assert RECORD_TEXT in _text(_online(config))
        assert RECORD_TEXT in _text(_batch(config))


class TestAnthropicRepairRound:
    """The repair call of a record, with prompt caching on."""

    @staticmethod
    def _config() -> dict[str, Any]:
        return _config("anthropic", json_mode=True, schema=True, enable_prompt_caching=True)

    @staticmethod
    def _online(config: dict[str, Any], repair_prompt: str) -> dict[str, Any]:
        with _online_wire("anthropic") as sent:
            run_dynamic_agent(
                config,
                "summarize",
                {"source": RECORD},
                repair_prompt,
                rendered_prompt=config["prompt"],
            )
        (body,) = sent
        return _asked("anthropic", body)

    @staticmethod
    def _batch(tmp_path: Any, config: dict[str, Any], feedback: Any) -> dict[str, Any]:
        client = _batch_client("anthropic", caching=True)
        prepared = BatchTaskPreparator(storage_backend=MagicMock()).prepare_tasks(
            agent_config=config,
            data=[{"target_id": "r1", "source_guid": "sg-1", "content": RECORD}],
            provider=client,
            output_directory=str(tmp_path),
            attempt=1,
            feedback_by_id={"r1": feedback},
        )
        (task,) = prepared.tasks
        return _asked("anthropic", task["params"])

    def test_the_feedback_lands_where_online_puts_it_with_the_same_cache_mark(self, tmp_path):
        config = self._config()

        online = self._online(config, f"{PROMPT}\n\n{FEEDBACK}")
        batch = self._batch(tmp_path, config, FEEDBACK)

        assert batch == online
        (message,) = online["messages"]
        marked, rest = message["content"]
        assert marked == {
            "type": "text",
            "text": f"\n<|begin_of_user_instruction|>: {PROMPT}",
            "cache_control": MARK,
        }
        assert rest["text"].startswith(f"\n\n{FEEDBACK} :<|end_of_user_instruction|>")
        assert online["system"] is None

    def test_a_repair_prompt_that_does_not_begin_with_the_prompt_carries_no_mark(self, tmp_path):
        config = self._config()

        online = self._online(config, f"Fix this.\n\n{PROMPT}")
        batch = self._batch(tmp_path, config, lambda prompt: f"Fix this.\n\n{prompt}")

        assert batch == online
        assert isinstance(online["messages"][0]["content"], str)


@pytest.mark.parametrize("vendor", VENDORS)
def test_a_judge_batch_line_carries_the_online_judge_request(vendor, tmp_path):
    config = _config(vendor, json_mode=True, schema=True, enable_prompt_caching=True)
    rule, value = "Every tag is one word.", {"tags": ["a b", "Café {x}"]}

    call = judge_call(rule, value, key="key")

    with _online_wire(vendor) as sent:
        OnlineSideCalls(config).run(call)
    (online,) = sent

    client = _batch_client(vendor, caching=True)
    with patch.object(client, "submit_batch", return_value=("b1", "submitted")) as submit:
        submit_side_batch(
            client,
            call.kind,
            {call.key: call},
            config,
            file_name="f",
            attempt=1,
            output_directory=str(tmp_path),
        )
    (task,) = submit.call_args.kwargs["tasks"]

    assert _asked(vendor, _batch_request(vendor, task)) == _asked(vendor, online)


# vendor, model, json_mode, prompt characters: each vendor's online client decides which
# context window a prompt is measured against.
SIZES = [
    ("openai", "gpt-4", True, 40_000),
    ("openai", "gpt-4", False, 40_000),
    ("openai", "gpt-4", False, 600_000),
    ("groq", "gemma2-9b-it", True, 40_000),
    ("groq", "gemma2-9b-it", False, 600_000),
    ("anthropic", "claude-sonnet-4-6", True, 600_000),
    ("anthropic", "claude-sonnet-4-6", False, 900_000),
    ("gemini", "gemini-2.5-flash", True, 600_000),
    ("ollama_local", "llama3", False, 600_000),
    ("ollama_cloud", "llama3", True, 600_000),
]


@pytest.mark.parametrize(("vendor", "model", "json_mode", "size"), SIZES)
def test_batch_refuses_the_prompt_online_refuses_as_too_large(
    vendor, model, json_mode, size, tmp_path
):
    config = _config(vendor, json_mode=json_mode, schema=json_mode, model_name=model)
    record = {"doc": "x" * size}

    with _online_wire(vendor) as sent:
        try:
            create_dynamic_agent(config, {"source": record}, PROMPT)
            online_refused = False
        except PromptTooLargeError:
            online_refused = True
    assert bool(sent) != online_refused

    prepared = BatchTaskPreparator(storage_backend=MagicMock()).prepare_tasks(
        agent_config=config,
        data=[{"target_id": "r1", "source_guid": "sg-1", "content": record}],
        provider=_batch_client(vendor),
        output_directory=str(tmp_path),
    )

    assert (len(prepared.tasks) == 0) == online_refused
    assert BatchContextMetadata.is_included(prepared.context_map["r1"]) != online_refused
