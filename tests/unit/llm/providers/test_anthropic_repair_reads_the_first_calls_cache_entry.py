"""A repair call sends its feedback after the marked prompt, so it reads the cache entry the first call wrote."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import anthropic
import openai
import pytest

from agent_actions.expectations.service import ExpectationService
from agent_actions.expectations.types import Suite
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.processing.invocation.online import OnlineStrategy
from agent_actions.processing.prepared_task import PreparedTask
from agent_actions.prompt.service import PromptPreparationService
from tests._support.sdk_http import http_library

MARK = {"type": "ephemeral"}
STATIC = "Summarise the page."
TEMPLATED = "Summarise the page {{ source.page_content }}."
FEEDBACK_START = "\n\n## Your previous output failed validation"
FEEDBACK = "Your previous output failed: the summary is empty."
PAGES = ("alpha", "beta")
SUITE = Suite(
    name="s",
    expectations=[
        {"id": "two_ideas", "type": "item_count", "field": "ideas", "params": {"min": 2}}
    ],
)
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
_ANTHROPIC_REPLY = {
    "id": "m",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-6",
    "content": [{"type": "text", "text": "ok"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}
_OPENAI_REPLY = {
    "id": "c",
    "object": "chat.completion",
    "created": 0,
    "model": "gpt-4o-mini",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def _config(prompt: str, *, vendor: str = "anthropic", caching: bool = True) -> dict[str, Any]:
    return {
        "agent_type": "summarize",
        "action_name": "summarize",
        "name": "summarize",
        "model_vendor": vendor,
        "model_name": "claude-sonnet-4-6" if vendor == "anthropic" else "gpt-4o-mini",
        "api_key": "TEST_PROVIDER_KEY",
        "json_mode": False,
        "granularity": "record",
        "enable_prompt_caching": caching,
        "prompt": prompt,
        "context_scope": {"observe": ["source.page_content"]},
    }


def _marked_texts(value: Any) -> list[str]:
    if isinstance(value, dict):
        own = [value["text"]] if "cache_control" in value else []
        return own + [t for v in value.values() for t in _marked_texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in _marked_texts(v)]
    return []


def _joined(content: str | list[dict[str, Any]]) -> str:
    return content if isinstance(content, str) else "".join(b["text"] for b in content)


def _sdk_client(vendor: str, sent: list[dict[str, Any]]) -> Any:
    http = http_library(anthropic if vendor == "anthropic" else openai)

    def handler(request: Any) -> Any:
        sent.append(json.loads(request.content))
        if request.url.path.endswith("/batches"):
            return http.Response(200, json=_BATCH_CREATED)
        return http.Response(200, json=_ANTHROPIC_REPLY if vendor == "anthropic" else _OPENAI_REPLY)

    http_client = http.Client(transport=http.MockTransport(handler))
    if vendor == "anthropic":
        return anthropic.Anthropic(api_key="sk-ant-test", http_client=http_client)
    return openai.OpenAI(api_key="sk-test", http_client=http_client)


def _online(config: dict[str, Any], repair: str | dict[str, Any] = "auto") -> list[dict[str, Any]]:
    """Send one record through the expectation repair loop; return the first and repair bodies."""
    sent: list[dict[str, Any]] = []
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
    )
    strategy = OnlineStrategy(
        expectation_service=ExpectationService(SUITE, repair=repair, max_iterations=2)
    )
    with patch(
        "agent_actions.llm.providers.client_base.get_or_create_client",
        lambda *_a, **_k: _sdk_client(config["model_vendor"], sent),
    ):
        strategy.invoke(task, context)
    assert len(sent) == 2
    return sent


def _anthropic_batch(
    tmp_path: Path, config: dict[str, Any], feedback: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    client = AnthropicBatchClient(
        api_key="sk-ant-test", enable_prompt_caching=config["enable_prompt_caching"]
    )
    client.client = _sdk_client("anthropic", sent)
    prepared = _prepare(tmp_path, config, client, feedback)
    client.submit_batch(prepared, "pages", str(tmp_path))
    (body,) = sent
    return [line["params"] for line in body["requests"]]


def _prepare(
    tmp_path: Path, config: dict[str, Any], client: Any, feedback: dict[str, str] | None
) -> list[dict[str, Any]]:
    data = [
        {"target_id": page, "source_guid": f"sg-{page}", "content": {"page_content": page}}
        for page in PAGES
    ]
    return (
        BatchTaskPreparator(action_indices={}, dependency_configs={}, storage_backend=MagicMock())
        .prepare_tasks(
            agent_config=config,
            data=data,
            provider=client,
            output_directory=str(tmp_path),
            attempt=1 if feedback else 0,
            feedback_by_id=feedback,
        )
        .tasks
    )


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "sk-test")


class TestOnlineRepair:
    def test_the_repair_call_marks_the_same_block_the_first_call_marked(self):
        first, repair = _online(_config(STATIC))

        assert _marked_texts(first) == _marked_texts(repair)
        assert len(_marked_texts(repair)) == 1
        assert _marked_texts(repair)[0].endswith(f": {STATIC}")

    def test_the_feedback_starts_an_unmarked_block_after_the_marked_prompt(self):
        _, repair = _online(_config(STATIC))

        content = repair["messages"][0]["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        marked, rest = content
        assert marked["cache_control"] == MARK
        assert "cache_control" not in rest
        assert rest["text"].startswith(FEEDBACK_START)

    def test_the_model_reads_the_same_repair_text_with_caching_on_or_off(self):
        on = _online(_config(STATIC))
        off = _online(_config(STATIC, caching=False))

        assert off[1]["messages"][0]["content"].startswith(
            f"\n<|begin_of_user_instruction|>: {STATIC}{FEEDBACK_START}"
        )
        assert [_joined(body["messages"][0]["content"]) for body in on] == [
            body["messages"][0]["content"] for body in off
        ]

    def test_caching_off_marks_neither_call(self):
        assert [_marked_texts(body) for body in _online(_config(STATIC, caching=False))] == [[], []]

    def test_a_repair_of_a_prompt_that_reads_the_record_carries_no_mark(self):
        first, repair = _online(_config(TEMPLATED))

        assert "alpha" in _joined(repair["messages"][0]["content"])
        assert FEEDBACK_START in _joined(repair["messages"][0]["content"])
        assert [_marked_texts(first), _marked_texts(repair)] == [[], []]

    def test_a_repair_template_that_does_not_begin_with_the_prompt_carries_no_mark(self):
        first, repair = _online(
            _config(STATIC), repair={"prompt": "Fix this.\n\n{original_prompt}\n\n{failed_lines}"}
        )

        assert _joined(repair["messages"][0]["content"]).startswith(
            "\n<|begin_of_user_instruction|>: Fix this.\n\n"
        )
        assert len(_marked_texts(first)) == 1
        assert _marked_texts(repair) == []

    def test_another_provider_sends_the_joined_repair_text_with_no_mark(self):
        first, repair = _online(_config(STATIC, vendor="openai"))

        content = repair["messages"][0]["content"]
        assert isinstance(content, str)
        assert content.startswith(f"\n<|begin_of_user_instruction|>: {STATIC}{FEEDBACK_START}")
        assert [_marked_texts(first), _marked_texts(repair)] == [[], []]


class TestBatchRepair:
    def test_the_repair_round_marks_the_same_block_the_first_round_marked(self, tmp_path):
        first = _anthropic_batch(tmp_path, _config(STATIC))
        repair = _anthropic_batch(
            tmp_path, _config(STATIC), feedback={page: FEEDBACK for page in PAGES}
        )

        assert [_marked_texts(p) for p in first] == [[STATIC], [STATIC]]
        assert [_marked_texts(p) for p in repair] == [[STATIC], [STATIC]]

    def test_the_feedback_is_its_own_unmarked_system_block(self, tmp_path):
        params = _anthropic_batch(
            tmp_path, _config(STATIC), feedback={page: FEEDBACK for page in PAGES}
        )

        assert [p["system"] for p in params] == [
            [
                {"type": "text", "text": STATIC, "cache_control": MARK},
                {"type": "text", "text": f"\n\n{FEEDBACK}"},
            ]
        ] * 2

    def test_the_model_reads_the_same_repair_text_with_caching_on_or_off(self, tmp_path):
        feedback = {page: FEEDBACK for page in PAGES}
        on = _anthropic_batch(tmp_path, _config(STATIC), feedback=feedback)
        off = _anthropic_batch(tmp_path, _config(STATIC, caching=False), feedback=feedback)

        assert [p["system"] for p in off] == [f"{STATIC}\n\n{FEEDBACK}"] * 2
        assert [_joined(p["system"]) for p in on] == [p["system"] for p in off]
        assert [p["messages"] for p in on] == [p["messages"] for p in off]

    def test_a_repair_round_of_a_prompt_that_reads_the_record_carries_no_mark(self, tmp_path):
        params = _anthropic_batch(
            tmp_path, _config(TEMPLATED), feedback={page: FEEDBACK for page in PAGES}
        )

        assert [p["system"] for p in params] == [
            f"Summarise the page {page}.\n\n{FEEDBACK}" for page in PAGES
        ]
        assert [_marked_texts(p) for p in params] == [[], []]

    def test_another_provider_sends_the_joined_repair_prompt_with_no_mark(self, tmp_path):
        tasks = _prepare(
            tmp_path,
            _config(STATIC, vendor="openai"),
            OpenAIBatchClient(api_key="sk-test"),
            {page: FEEDBACK for page in PAGES},
        )

        assert [task["body"]["messages"][0] for task in tasks] == [
            {"role": "system", "content": f"{STATIC}\n\n{FEEDBACK}"}
        ] * 2
        assert [_marked_texts(task) for task in tasks] == [[], []]
