"""A prompt template with no `{% cache_point %}` sends the request the default cache rules give."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.processing.invocation.online import OnlineStrategy
from agent_actions.processing.prepared_task import PreparedTask
from agent_actions.prompt.cache_scope import CACHE_POINTS_KEY
from agent_actions.prompt.message_builder import PROVIDER_MESSAGE_CONFIGS, MessageBuilder
from agent_actions.prompt.service import PromptPreparationService
from tests._support.sdk_http import http_library

MARK = {"type": "ephemeral"}
MODEL = "claude-sonnet-4-6"
PER_RECORD = "Summarise the page {{ source.page_content }}."
STATIC = "Summarise the page."
# The user message of each prompt, with no cache point in the template.
PER_RECORD_TEXT = (
    "\n<|begin_of_user_instruction|>: Summarise the page alpha. :<|end_of_user_instruction|>\n"
    '<|begin_of_text|>: {"source": {"page_content": "alpha"}} :<|end_of_text|>\n'
)
STATIC_BLOCKS = [
    {
        "type": "text",
        "text": "\n<|begin_of_user_instruction|>: Summarise the page.",
        "cache_control": MARK,
    },
    {
        "type": "text",
        "text": " :<|end_of_user_instruction|>\n"
        '<|begin_of_text|>: {"source": {"page_content": "alpha"}} :<|end_of_text|>\n',
    },
]
_REPLY = {
    "id": "m",
    "type": "message",
    "role": "assistant",
    "model": MODEL,
    "content": [{"type": "text", "text": "ok"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}
_BATCH_CREATED = {
    "id": "msgbatch_1",
    "type": "message_batch",
    "processing_status": "in_progress",
    "request_counts": {"processing": 1, "succeeded": 0, "errored": 0, "canceled": 0, "expired": 0},
    "created_at": "2026-01-01T00:00:00Z",
    "expires_at": "2026-01-02T00:00:00Z",
    "ended_at": None,
    "archived_at": None,
    "cancel_initiated_at": None,
    "results_url": None,
}


def _config(prompt: str, caching: bool) -> dict[str, Any]:
    return {
        "agent_type": "summarize",
        "action_name": "summarize",
        "name": "summarize",
        "model_vendor": "anthropic",
        "model_name": MODEL,
        "api_key": "TEST_PROVIDER_KEY",
        "json_mode": False,
        "granularity": "record",
        "enable_prompt_caching": caching,
        "prompt": prompt,
        "context_scope": {"observe": ["source.page_content"]},
        # Every observed field goes in the context block, also the field the prompt prints.
        "context_block": "all",
    }


def _sdk_client(sent: list[dict[str, Any]]) -> anthropic.Anthropic:
    http = http_library(anthropic)

    def handler(request: Any) -> Any:
        sent.append(json.loads(request.content))
        created = request.url.path.endswith("/batches")
        return http.Response(200, json=_BATCH_CREATED if created else _REPLY)

    return anthropic.Anthropic(
        api_key="sk-ant-test", http_client=http.Client(transport=http.MockTransport(handler))
    )


def _online(prompt: str, caching: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """The request body one record sends online, and the config its client was handed."""
    sent: list[dict[str, Any]] = []
    config = _config(prompt, caching)
    prepared = PromptPreparationService.prepare_prompt_with_field_context(
        config, "summarize", {}, field_context={"source": {"page_content": "alpha"}}
    )
    context = MagicMock()
    context.agent_name = "summarize"
    context.agent_config = config
    context.storage_backend = None
    task = PreparedTask(
        target_id="alpha",
        source_guid="sg-alpha",
        formatted_prompt=prepared.formatted_prompt,
        llm_context=prepared.llm_context,
        cache_points=prepared.cache_points,
    )
    handed: list[dict[str, Any]] = []
    from agent_actions.llm.providers.anthropic.client import AnthropicClient

    call = AnthropicClient.call_non_json

    def recording(api_key: Any, agent_config: dict[str, Any], *rest: Any) -> Any:
        handed.append(agent_config)
        return call(api_key, agent_config, *rest)

    with (
        patch(
            "agent_actions.llm.providers.client_base.get_or_create_client",
            lambda *_a, **_k: _sdk_client(sent),
        ),
        patch.object(AnthropicClient, "call_non_json", recording),
    ):
        OnlineStrategy().invoke(task, context)
    (body,) = sent
    (config_handed,) = handed
    return body, config_handed


def _batch(tmp_path: Path, prompt: str, caching: bool) -> dict[str, Any]:
    sent: list[dict[str, Any]] = []
    client = AnthropicBatchClient(api_key="sk-ant-test", enable_prompt_caching=caching)
    client.client = _sdk_client(sent)
    data = [{"target_id": "alpha", "source_guid": "sg-alpha", "content": {"page_content": "alpha"}}]
    prepared = BatchTaskPreparator(
        action_indices={}, dependency_configs={}, storage_backend=MagicMock()
    ).prepare_tasks(
        agent_config=_config(prompt, caching),
        data=data,
        provider=client,
        output_directory=str(tmp_path),
    )
    client.submit_batch(prepared.tasks, "pages", str(tmp_path))
    (body,) = sent
    (line,) = body["requests"]
    return line


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "sk-test")


@pytest.mark.parametrize("caching", [True, False], ids=["caching-on", "caching-off"])
def test_a_prompt_that_reads_the_record_goes_online_as_one_unmarked_text(caching):
    body, handed = _online(PER_RECORD, caching)

    assert {key: body[key] for key in ("model", "max_tokens", "messages")} == {
        "model": MODEL,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": PER_RECORD_TEXT}],
    }
    assert set(body) == {"model", "max_tokens", "messages"}
    assert CACHE_POINTS_KEY not in handed


def test_a_prompt_every_record_shares_goes_online_marked_at_its_end_only():
    body, handed = _online(STATIC, True)

    assert body["messages"] == [{"role": "user", "content": STATIC_BLOCKS}]
    assert CACHE_POINTS_KEY not in handed


def test_a_prompt_every_record_shares_goes_online_unmarked_with_caching_off():
    body, _ = _online(STATIC, False)

    assert body["messages"] == [
        {"role": "user", "content": "".join(block["text"] for block in STATIC_BLOCKS)}
    ]


@pytest.mark.parametrize("caching", [True, False], ids=["caching-on", "caching-off"])
def test_a_prompt_that_reads_the_record_goes_into_a_batch_file_as_one_unmarked_text(
    tmp_path, caching
):
    assert _batch(tmp_path, PER_RECORD, caching) == {
        "custom_id": "alpha",
        "params": {
            "model": MODEL,
            "messages": [{"role": "user", "content": PER_RECORD_TEXT}],
            "max_tokens": 4096,
        },
    }


def test_a_prompt_every_record_shares_goes_into_a_batch_file_marked_at_its_end_only(tmp_path):
    assert _batch(tmp_path, STATIC, True)["params"]["messages"] == [
        {"role": "user", "content": STATIC_BLOCKS}
    ]


@pytest.mark.parametrize("provider", sorted(PROVIDER_MESSAGE_CONFIGS))
@pytest.mark.parametrize("json_mode", [True, False], ids=["json", "text"])
@pytest.mark.parametrize("caching", [True, False], ids=["caching-on", "caching-off"])
def test_the_builder_gives_what_it_gave_when_handed_no_cache_points(provider, json_mode, caching):
    plain = MessageBuilder.build(
        provider, STATIC, {"a": 1}, json_mode=json_mode, enable_prompt_caching=caching
    )
    with_none = MessageBuilder.build(
        provider,
        STATIC,
        {"a": 1},
        json_mode=json_mode,
        enable_prompt_caching=caching,
        cache_points=(),
    )

    assert with_none == plain
