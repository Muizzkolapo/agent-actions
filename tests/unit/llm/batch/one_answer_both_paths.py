"""One vendor response, put through that vendor's online client and its batch client.

Each response is the body the vendor's API returns. Online, the real client reads it from
a stubbed SDK call; in batch, the real batch client reads it from a result line and the
retrieval step settles it for the action's mode. `End` is how the record then ends.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

from anthropic.types import Message as AnthropicMessage
from google.genai import types as gemini_types
from groq.types.chat import ChatCompletion as GroqChatCompletion
from ollama import ChatResponse
from openai.types.chat import ChatCompletion as OpenAIChatCompletion

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchResultStrategy,
    validated_items,
)
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.batch.services import retry_ops
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.shared import settle_unanswered
from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.anthropic.client import AnthropicClient
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient
from agent_actions.llm.providers.gemini.client import GeminiClient
from agent_actions.llm.providers.groq.batch_client import GroqBatchClient
from agent_actions.llm.providers.groq.client import GroqClient
from agent_actions.llm.providers.ollama.batch_client import OllamaBatchClient
from agent_actions.llm.providers.ollama.client import OllamaLocalClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.llm.providers.openai.client import OpenAIClient
from agent_actions.processing.helpers import _is_empty_output
from agent_actions.processing.recovery.retry import is_retriable_error
from agent_actions.processing.types import ProcessingResult

CONFIG: dict[str, Any] = {"model_name": "m", "agent_type": "act", "action_name": "act"}
RECORD_ID = "r1"


@dataclass(frozen=True)
class End:
    """How one record ends: an answer stored, an empty answer, or a failure."""

    stored: list[Any] | None = None
    # Handed to the action's on_empty.
    empty: bool = False
    error: str | None = None
    # A `retry:` block sends the record again.
    resent: bool = False


# -- response bodies ---------------------------------------------------------


def chat_completion(
    content: str | None, finish_reason: str = "stop", refusal: str | None = None
) -> dict[str, Any]:
    """An OpenAI or Groq chat completion."""
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "m-2026",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
            }
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    }


def gemini_response(
    parts: list[dict[str, Any]] | None,
    finish_reason: str | None = "STOP",
    block_reason: str | None = None,
) -> dict[str, Any]:
    """A Gemini generateContent response; *parts* None is a response with no candidate."""
    body: dict[str, Any] = {
        "modelVersion": "m-2026",
        "usageMetadata": {
            "promptTokenCount": 7,
            "candidatesTokenCount": 3,
            "thoughtsTokenCount": 5,
            "totalTokenCount": 15,
        },
    }
    if parts is not None:
        candidate: dict[str, Any] = {"index": 0}
        if parts:
            candidate["content"] = {"role": "model", "parts": parts}
        if finish_reason:
            candidate["finishReason"] = finish_reason
        body["candidates"] = [candidate]
    if block_reason:
        body["promptFeedback"] = {"blockReason": block_reason}
    return body


def anthropic_message(
    content: list[dict[str, Any]],
    stop_reason: str = "end_turn",
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "m-2026",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage or {"input_tokens": 7, "output_tokens": 3},
    }


def ollama_response(content: str, done_reason: str = "stop") -> dict[str, Any]:
    return {
        "model": "m",
        "created_at": "2026-01-01T00:00:00Z",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": done_reason,
        "prompt_eval_count": 7,
        "eval_count": 3,
    }


# -- the two paths -----------------------------------------------------------


# vendor: its online client, where the client builds its SDK, the SDK call it makes
# and the response type that call returns.
_ONLINE: dict[str, tuple[Any, str, str, Any]] = {
    "openai": (
        OpenAIClient,
        "agent_actions.llm.providers.openai.client.OpenAI",
        "chat.completions.create",
        OpenAIChatCompletion,
    ),
    "groq": (
        GroqClient,
        "agent_actions.llm.providers.groq.client.Groq",
        "chat.completions.create",
        GroqChatCompletion,
    ),
    "gemini": (
        GeminiClient,
        "agent_actions.llm.providers.gemini.client._build_client",
        "models.generate_content",
        gemini_types.GenerateContentResponse,
    ),
    "anthropic": (AnthropicClient, "anthropic.Anthropic", "messages.create", AnthropicMessage),
    "ollama_local": (
        OllamaLocalClient,
        "agent_actions.llm.providers.ollama.client.Client",
        "chat",
        ChatResponse,
    ),
}


def online_answer(
    vendor: str, body: dict[str, Any], *, json_mode: bool, config: dict[str, Any] | None = None
) -> list[Any]:
    """What the online client returns for *body*; raises what it raises."""
    agent_config = {**CONFIG, "model_vendor": vendor, "json_mode": json_mode, **(config or {})}
    client, sdk_path, call_path, response_type = _ONLINE[vendor]
    with patch.dict(client_base._client_cache, clear=True), patch(sdk_path) as sdk:
        call = sdk.return_value
        for name in call_path.split("."):
            call = getattr(call, name)
        call.return_value = response_type.model_validate(body)
        if json_mode:
            return client.call_json("k", agent_config, "p", {"t": "x"}, None)  # type: ignore[no-any-return]
        return client.call_non_json("k", agent_config, "p", {"t": "x"})  # type: ignore[no-any-return]


def _bare(cls: type) -> Any:
    return cls.__new__(cls)


def batch_line(vendor: str, body: dict[str, Any]) -> BatchResult:
    """The batch client's reading of the result line that carries *body*."""
    if vendor in ("openai", "groq"):
        client = _bare(OpenAIBatchClient if vendor == "openai" else GroqBatchClient)
        line = {"custom_id": RECORD_ID, "response": {"status_code": 200, "body": body}}
        return client.parse_provider_response(line)  # type: ignore[no-any-return]
    if vendor == "gemini":
        return _bare(GeminiBatchClient).parse_provider_response(  # type: ignore[no-any-return]
            {"key": RECORD_ID, "response": body}
        )
    if vendor == "anthropic":
        return _bare(AnthropicBatchClient).parse_provider_response(  # type: ignore[no-any-return]
            {"custom_id": RECORD_ID, "result": {"type": "succeeded", "message": body}}
        )
    ollama = OllamaBatchClient(base_url="http://localhost:11434")
    ollama.client = MagicMock()
    ollama.client.chat.return_value = ChatResponse.model_validate(body)
    (task,) = ollama.prepare_tasks(
        [{"target_id": RECORD_ID, "content": {"t": "x"}, "prompt": "p"}],
        {"model_name": "m", "json_mode": False},
    )
    line = ollama._process_single_task(task, 0, 1)
    assert line is not None
    return ollama.parse_provider_response(line)


def batch_result(vendor: str, body: dict[str, Any], *, json_mode: bool) -> BatchResult:
    """The batch line for *body*, settled for the action's mode as retrieval settles it."""
    result = batch_line(vendor, body)
    settle_unanswered([result], json_mode=json_mode)
    return result


def online_end(vendor: str, body: dict[str, Any], *, json_mode: bool) -> End:
    try:
        answer = online_answer(vendor, body, json_mode=json_mode)
    except Exception as error:
        return End(error=str(error), resent=is_retriable_error(error))
    if _is_empty_output(answer):
        return End(empty=True)
    return End(stored=answer)


def batch_end(vendor: str, body: dict[str, Any], *, json_mode: bool) -> End:
    result = batch_result(vendor, body, json_mode=json_mode)
    if not BatchResultReconciler.is_answered(result):
        return End(error=result.error, resent=BatchResultReconciler.is_retriable(result))
    items = validated_items(result.content, json_mode=json_mode, output_field="raw_response")
    if not items:
        return End(empty=True)
    return End(stored=items)


# -- a collect pass over one returned batch ------------------------------------

FILE_NAME = "pages.json"
CONTEXT_MAP: dict[str, Any] = {
    RECORD_ID: {
        "target_id": RECORD_ID,
        "source_guid": "guid-1",
        "user_content": "one",
        "content": {"source": {"page": "p1"}},
    }
}


class _MetadataBackend:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def load_metadata(self, key: str) -> str | None:
        return self.store.get(key)

    def save_metadata(self, key: str, value: str) -> None:
        self.store[key] = value

    def delete_metadata(self, key: str) -> bool:
        return self.store.pop(key, None) is not None


class CollectPass:
    """One collect pass over a returned batch holding *lines*, deciding recovery for real.

    Records what it would send again (`resent`), what it would regenerate and with which
    feedback (`repaired`), and the results it hands to the writer (`written`).
    """

    def __init__(self, lines: list[BatchResult], agent_config: dict[str, Any]) -> None:
        self.agent_config = agent_config
        self.action = agent_config["action_name"]
        self.resent: list[set[str]] = []
        self.repaired: list[tuple[BatchResult, Any]] = []
        self.written: list[BatchResult] = []
        self.exhausted: dict[str, Any] | None = None

        backend = _MetadataBackend()
        entry = BatchJobEntry(
            batch_id="batch_parent",
            status=BatchStatus.COMPLETED,
            timestamp="2026-09-01T09:00:00+00:00",
            provider="openai",
            record_count=len(lines),
            file_name=FILE_NAME,
        )
        backend.store[f"{BatchRegistryManager.METADATA_KEY_PREFIX}{self.action}"] = json.dumps(
            {FILE_NAME: entry.to_dict()}
        )
        manager = BatchRegistryManager(backend, self.action)
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED
        provider.retrieve_results.return_value = lines

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=lambda _: manager,
            storage_backend=backend,
            workflow_name=self.action,
        )
        service._client_resolver.get_for_batch_id.return_value = provider
        service._context_manager.load_batch_context_map.return_value = CONTEXT_MAP
        retry_service = MagicMock()
        retry_service.submit_retry_batch.side_effect = self._submit_retry
        retry_service.process_retry_results.side_effect = retry_ops.process_retry_results
        retry_service.build_exhausted_recovery.side_effect = retry_ops.build_exhausted_recovery
        service._retry_service = retry_service
        self._service = service

    def _submit_retry(self, *, missing_ids: set[str], **_kw: Any) -> tuple[str, int]:
        self.resent.append(set(missing_ids))
        return ("batch_retry", len(missing_ids))

    def _submit_repair(
        self, *, failed_results: list[BatchResult], strategy: Any, **_kw: Any
    ) -> None:
        self.repaired.extend((result, strategy.build_feedback(result)) for result in failed_results)

    def _write(self, batch_results: list[BatchResult], **kw: Any) -> tuple[list, Any, None]:
        self.written = batch_results
        self.exhausted = kw.get("exhausted_recovery")
        return ([], MagicMock(), None)

    def run(self) -> CollectPass:
        with (
            patch(
                "agent_actions.llm.batch.services.repair_ops.submit_repair_batch",
                side_effect=self._submit_repair,
            ),
            patch.object(
                self._service, "_convert_batch_results_to_workflow_format", side_effect=self._write
            ),
            patch.object(self._service, "_write_batch_output"),
        ):
            self._service.process_all_batch_results(
                "/out", self.agent_config, action_name=self.action
            )
        return self

    def processed(self) -> ProcessingResult:
        """The written record as the result strategy reads it."""
        (result,) = BatchResultStrategy().process(
            self.written,
            context_map=CONTEXT_MAP,
            agent_config=self.agent_config,
            exhausted_recovery=self.exhausted,
        )
        return result
