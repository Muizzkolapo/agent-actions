"""A prompt-cache mark goes only on a prompt that is the same for every record, online and in batch."""

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
from agent_actions.prompt.service import PromptPreparationService
from agent_actions.validation.static_analyzer.workflow_static_analyzer import analyze_workflow
from tests._support.sdk_http import http_library

# The HTTP library the installed anthropic SDK runs on: httpx, or httpx2 on 1.x.
httpx = http_library(anthropic)

MODEL = "claude-sonnet-4-6"
MARK = {"type": "ephemeral"}
TEMPLATED = "Summarise the page {{ source.page_content }}."
STATIC = "Summarise the page."
PAGES = ("alpha-page", "beta-page")
PICK_SCHEMA = 'def pick_schema(context_json):\n    return "topic_answer"\n'
_BATCH_CREATED = {
    "id": "msgbatch_1",
    "type": "message_batch",
    "processing_status": "in_progress",
    "request_counts": {"processing": 2, "succeeded": 0, "errored": 0, "canceled": 0, "expired": 0},
    "created_at": "2026-01-01T00:00:00Z",
    "expires_at": "2026-01-02T00:00:00Z",
    "ended_at": None,
    "archived_at": None,
    "cancel_initiated_at": None,
    "results_url": None,
}


def _config(prompt: str, **extra: Any) -> dict[str, Any]:
    return {
        "agent_type": "summarize",
        "action_name": "summarize",
        "name": "summarize",
        "model_vendor": "anthropic",
        "model_name": MODEL,
        "api_key": "TEST_ANTHROPIC_KEY",
        "json_mode": False,
        "granularity": "record",
        "enable_prompt_caching": True,
        "prompt": prompt,
        "context_scope": {"observe": ["source.page_content"]},
        **extra,
    }


def _marked_texts(value: Any) -> list[str]:
    if isinstance(value, dict):
        own = [value["text"]] if "cache_control" in value else []
        return own + [t for v in value.values() for t in _marked_texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in _marked_texts(v)]
    return []


def _all_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "".join(_all_text(v) for v in value.values())
    if isinstance(value, list):
        return "".join(_all_text(v) for v in value)
    return ""


def _transport(sent: list[dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(body)
        if request.url.path.endswith("/batches"):
            return httpx.Response(200, json=_BATCH_CREATED)
        block = (
            {
                "type": "tool_use",
                "id": "t",
                "name": body["tools"][0]["name"],
                "input": {"topic": "x"},
            }
            if "tools" in body
            else {"type": "text", "text": "ok"}
        )
        return httpx.Response(
            200,
            json={
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": MODEL,
                "content": [block],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    return httpx.MockTransport(handler)


def _sdk(sent: list[dict[str, Any]]) -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key="sk-ant-test", http_client=httpx.Client(transport=_transport(sent))
    )


def _online(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Render each page's prompt and send it online; return each request body."""
    sent: list[dict[str, Any]] = []
    for page in PAGES:
        prepared = PromptPreparationService.prepare_prompt_with_field_context(
            config, "summarize", {}, field_context={"source": {"page_content": page}}
        )
        context = MagicMock()
        context.agent_name = "summarize"
        context.agent_config = config
        task = PreparedTask(
            target_id=page,
            source_guid=f"sg-{page}",
            formatted_prompt=prepared.formatted_prompt,
            llm_context=prepared.llm_context,
        )
        strategy = OnlineStrategy()
        with patch(
            "agent_actions.llm.providers.client_base.get_or_create_client",
            lambda *_a, **_k: _sdk(sent),
        ):
            strategy.invoke(task, context)
    return sent


def _batch(tmp_path: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Prepare every page as one batch round and submit it; return each request's params."""
    sent: list[dict[str, Any]] = []
    client = AnthropicBatchClient(api_key="sk-ant-test", enable_prompt_caching=True)
    client.client = _sdk(sent)
    data = [
        {"target_id": page, "source_guid": f"sg-{page}", "content": {"page_content": page}}
        for page in PAGES
    ]
    prepared = BatchTaskPreparator(
        action_indices={}, dependency_configs={}, storage_backend=MagicMock()
    ).prepare_tasks(
        agent_config=config,
        data=data,
        provider=client,
        output_directory=str(tmp_path),
        attempt=0,
    )
    client.submit_batch(prepared.tasks, "pages", str(tmp_path))
    (body,) = sent
    return [line["params"] for line in body["requests"]]


def _dispatch_project(root: Path) -> dict[str, Any]:
    (root / "agent_actions.yml").write_text("schema_path: schema\n")
    (root / "schema").mkdir()
    (root / "schema" / "topic_answer.yml").write_text(
        "name: topic_answer\nfields:\n  - id: topic\n    type: string\n"
    )
    (root / "tools").mkdir()
    (root / "tools" / "pick_schema.py").write_text(PICK_SCHEMA)
    return {
        "json_mode": True,
        "schema": "dispatch_task('pick_schema')",
        "schema_options": ["topic_answer"],
        "tool_path": [str(root / "tools")],
        "_project_root": str(root),
    }


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "sk-ant-test")


class TestOnline:
    def test_a_prompt_that_reads_the_record_carries_no_mark(self):
        bodies = _online(_config(TEMPLATED))

        assert [
            page in _all_text(body["messages"]) for body, page in zip(bodies, PAGES, strict=True)
        ] == [
            True,
            True,
        ]
        assert [_marked_texts(body) for body in bodies] == [[], []]

    def test_a_static_prompt_keeps_one_mark_the_same_for_both_records(self):
        bodies = _online(_config(STATIC))

        marked = [_marked_texts(body) for body in bodies]
        assert len(marked[0]) == 1
        assert marked[0] == marked[1]
        assert STATIC in marked[0][0]

    def test_a_schema_each_record_chooses_places_no_mark(self, tmp_path):
        bodies = _online(_config(STATIC, **_dispatch_project(tmp_path)))

        assert [body["tools"][0]["name"] for body in bodies] == ["topic_answer"] * 2
        assert [_marked_texts(body) for body in bodies] == [[], []]


class TestBatch:
    def test_a_prompt_that_reads_the_record_carries_no_mark(self, tmp_path):
        params = _batch(tmp_path, _config(TEMPLATED))

        assert [p["system"] for p in params] == [f"Summarise the page {page}." for page in PAGES]
        assert [_marked_texts(p) for p in params] == [[], []]

    def test_a_static_prompt_keeps_one_mark_the_same_for_both_records(self, tmp_path):
        params = _batch(tmp_path, _config(STATIC))

        assert [_marked_texts(p) for p in params] == [[STATIC], [STATIC]]

    def test_a_schema_each_record_chooses_places_no_mark(self, tmp_path):
        params = _batch(tmp_path, _config(STATIC, **_dispatch_project(tmp_path)))

        assert [p["tools"][0]["name"] for p in params] == ["topic_answer"] * 2
        assert [_marked_texts(p) for p in params] == [[], []]


def _warnings(prompt: str, **extra: Any) -> list[str]:
    action = {
        "name": "summarize",
        "model_vendor": "anthropic",
        "enable_prompt_caching": True,
        "prompt": prompt,
        "context_scope": {"observe": ["source.page_content"]},
        "schema": {"summary": "string"},
        **extra,
    }
    result = analyze_workflow({"name": "pages", "actions": [action]})
    return [w.message for w in result.warnings if "enable_prompt_caching" in w.message]


class TestPreflightWarning:
    def test_a_cached_prompt_that_reads_source_is_named_with_its_fields(self):
        messages = _warnings("Summarise {{ source.page_content }} from {{ source.url }}.")

        assert len(messages) == 1
        assert messages[0].startswith("Action 'summarize' has enable_prompt_caching on")
        assert "source.page_content, source.url" in messages[0]

    def test_a_cached_static_prompt_raises_no_warning(self):
        assert _warnings("Summarise the page for {{ seed.exam.name }}.") == []

    def test_caching_off_raises_no_warning(self):
        assert _warnings("Summarise {{ source.page_content }}.", enable_prompt_caching=False) == []
