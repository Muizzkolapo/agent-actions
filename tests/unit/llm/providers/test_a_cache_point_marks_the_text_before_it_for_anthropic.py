"""A `{% cache_point %}` ends an Anthropic text block that carries a cache mark, online and in a batch file.

Two records that share the page before the point send that block byte for byte, which is
what lets the second read the cache entry the first wrote. No test here calls the API:
that the second response reports `cache_read_input_tokens` above 0 is not verified.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import anthropic
import openai
import pytest
from anthropic.types import TextBlockParam
from anthropic.types.messages.batch_create_params import Request
from pydantic import TypeAdapter

from agent_actions.expectations.service import ExpectationService
from agent_actions.expectations.types import Suite
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.providers.anthropic import MAX_CACHE_BREAKPOINTS, message_params
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.processing.invocation.online import OnlineStrategy
from agent_actions.processing.prepared_task import PreparedTask
from agent_actions.prompt.cache_scope import (
    CACHE_POINTS_KEY,
    REQUEST_VARIES_PER_RECORD_KEY,
    cache_points_of,
)
from agent_actions.prompt.message_builder import (
    PROVIDER_MESSAGE_CONFIGS,
    LLMMessage,
    LLMMessageEnvelope,
    MessageBuilder,
)
from agent_actions.prompt.service import PromptPreparationService
from tests._support.sdk_http import http_library

MARK = {"type": "ephemeral"}
PAGE = "The page text.\nIts second line."
WITH_POINT = """\
## PAGE
{{ source.page_content }}
{% cache_point %}
## THE SLOT
{{ source.fact }}
"""
WITHOUT_POINT = WITH_POINT.replace("{% cache_point %}\n", "")
STATIC_WITH_POINT = "Rules of the house.\n{% cache_point %}\nAnswer in one line."
# The text every record of PAGE sends before the point, online and in a batch file.
SHARED = f"\n<|begin_of_user_instruction|>: ## PAGE\n{PAGE}\n"
RECORDS = (
    {"target_id": "one", "page_content": PAGE, "fact": "It rained."},
    {"target_id": "two", "page_content": PAGE, "fact": "It snowed."},
)
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
        "agent_type": "write",
        "action_name": "write",
        "name": "write",
        "model_vendor": vendor,
        "model_name": "claude-sonnet-4-6" if vendor == "anthropic" else "gpt-4o-mini",
        "api_key": "TEST_PROVIDER_KEY",
        "json_mode": False,
        "granularity": "record",
        "enable_prompt_caching": caching,
        "prompt": prompt,
        "context_scope": {"observe": ["source.page_content", "source.fact"]},
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


def _sdk_client(vendor: str, sent: list[bytes]) -> Any:
    http = http_library(anthropic if vendor == "anthropic" else openai)

    def handler(request: Any) -> Any:
        sent.append(request.content)
        if request.url.path.endswith("/batches"):
            return http.Response(200, json=_BATCH_CREATED)
        return http.Response(200, json=_ANTHROPIC_REPLY if vendor == "anthropic" else _OPENAI_REPLY)

    http_client = http.Client(transport=http.MockTransport(handler))
    if vendor == "anthropic":
        return anthropic.Anthropic(api_key="sk-ant-test", http_client=http_client)
    return openai.OpenAI(api_key="sk-test", http_client=http_client)


def _online_bytes(
    config: dict[str, Any], record: dict[str, str], repair: str | None = None
) -> list[bytes]:
    """The request bodies one record sends online, as the SDK wrote them."""
    sent: list[bytes] = []
    source = {key: value for key, value in record.items() if key != "target_id"}
    prepared = PromptPreparationService.prepare_prompt_with_field_context(
        config, "write", {}, field_context={"source": source}
    )
    context = MagicMock()
    context.agent_name = "write"
    context.agent_config = config
    context.storage_backend = None
    task = PreparedTask(
        target_id=record["target_id"],
        source_guid=f"sg-{record['target_id']}",
        formatted_prompt=prepared.formatted_prompt,
        llm_context=prepared.llm_context,
        cache_points=prepared.cache_points,
    )
    service = (
        ExpectationService(SUITE, repair=repair, max_iterations=2) if repair is not None else None
    )
    with patch(
        "agent_actions.llm.providers.client_base.get_or_create_client",
        lambda *_a, **_k: _sdk_client(config["model_vendor"], sent),
    ):
        OnlineStrategy(expectation_service=service).invoke(task, context)
    return sent


def _online(config: dict[str, Any], record: dict[str, str] = RECORDS[0]) -> dict[str, Any]:
    (body,) = _online_bytes(config, record)
    return json.loads(body)


def _batch_tasks(
    tmp_path: Path, config: dict[str, Any], client: Any, feedback: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    data = [
        {
            "target_id": record["target_id"],
            "source_guid": f"sg-{record['target_id']}",
            "content": {key: value for key, value in record.items() if key != "target_id"},
        }
        for record in RECORDS
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


def _batch_file(
    tmp_path: Path, config: dict[str, Any], feedback: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """The requests of the batch input file agac writes, which are the ones it submits."""
    sent: list[bytes] = []
    client = AnthropicBatchClient(
        api_key="sk-ant-test", enable_prompt_caching=config["enable_prompt_caching"]
    )
    client.client = _sdk_client("anthropic", sent)
    files: list[Any] = []
    submit = client._submit_to_provider_api

    def reading_the_file(input_file: Path, batch_name: str) -> tuple[str, str]:
        files.append(json.loads(input_file.read_text(encoding="utf-8"))["requests"])
        return submit(input_file, batch_name)

    with patch.object(client, "_submit_to_provider_api", reading_the_file):
        client.submit_batch(
            _batch_tasks(tmp_path, config, client, feedback), "pages", str(tmp_path)
        )
    (written,) = files
    (body,) = sent
    assert json.loads(body)["requests"] == written
    return written


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "sk-test")


class TestOnline:
    def test_the_text_before_the_point_is_a_marked_block_and_the_rest_is_not(self):
        (message,) = _online(_config(WITH_POINT))["messages"]

        assert message == {
            "role": "user",
            "content": [
                {"type": "text", "text": SHARED, "cache_control": MARK},
                {
                    "type": "text",
                    "text": "## THE SLOT\nIt rained.\n :<|end_of_user_instruction|>\n"
                    '<|begin_of_text|>: {"source": {"page_content": '
                    '"The page text.\\nIts second line.", "fact": "It rained."}}'
                    " :<|end_of_text|>\n",
                },
            ],
        }

    def test_the_blocks_are_ones_the_sdk_request_type_takes(self):
        (message,) = _online(_config(WITH_POINT))["messages"]

        for block in message["content"]:
            TypeAdapter(TextBlockParam).validate_python(block, strict=True)

    def test_two_records_of_one_page_send_the_same_bytes_up_to_the_mark(self):
        (first,) = _online_bytes(_config(WITH_POINT), RECORDS[0])
        (second,) = _online_bytes(_config(WITH_POINT), RECORDS[1])

        shared = os.path.commonprefix([first, second])
        marked_block = json.dumps(
            {"type": "text", "text": SHARED, "cache_control": MARK}, separators=(",", ":")
        ).encode()
        assert shared.endswith(marked_block + b',{"type":"text","text":"## THE SLOT\\nIt ')
        assert first != second

    def test_two_records_of_one_page_mark_the_same_block_and_differ_after_it(self):
        first = _online(_config(WITH_POINT), RECORDS[0])["messages"][0]["content"]
        second = _online(_config(WITH_POINT), RECORDS[1])["messages"][0]["content"]

        assert first[0] == second[0]
        assert first[0]["cache_control"] == MARK
        assert first[1] != second[1]

    def test_a_record_of_another_page_marks_another_block(self):
        other = {**RECORDS[0], "page_content": "Another page."}

        assert _marked_texts(_online(_config(WITH_POINT), other)) != [SHARED]

    def test_the_model_reads_the_text_it_reads_without_the_tag(self):
        marked = _online(_config(WITH_POINT))["messages"][0]["content"]
        plain = _online(_config(WITHOUT_POINT, caching=False))["messages"][0]["content"]

        assert isinstance(plain, str)
        assert _joined(marked) == plain

    def test_with_caching_off_the_request_is_the_one_sent_without_the_tag(self):
        (marked,) = _online_bytes(_config(WITH_POINT, caching=False), RECORDS[0])
        (plain,) = _online_bytes(_config(WITHOUT_POINT, caching=False), RECORDS[0])

        assert marked == plain
        assert b"cache_control" not in marked

    def test_a_prompt_every_record_shares_is_marked_at_the_point_and_at_its_end(self):
        content = _online(_config(STATIC_WITH_POINT))["messages"][0]["content"]

        assert [block.get("cache_control") for block in content] == [MARK, MARK, None]
        assert [block["text"] for block in content[:2]] == [
            "\n<|begin_of_user_instruction|>: Rules of the house.\n",
            "Answer in one line.",
        ]

    def test_the_most_points_a_template_may_hold_fit_the_breakpoints_of_a_request(self):
        prompt = "a\n{% cache_point %}\nb\n{% cache_point %}\nc\n{% cache_point %}\nd"

        assert len(_marked_texts(_online(_config(prompt)))) == MAX_CACHE_BREAKPOINTS

    def test_a_repair_call_marks_the_block_the_first_call_marked(self):
        first, repair = (
            json.loads(body)
            for body in _online_bytes(_config(WITH_POINT), RECORDS[0], repair="auto")
        )

        assert _marked_texts(first) == _marked_texts(repair) == [SHARED]
        assert "failed validation" in _joined(repair["messages"][0]["content"])


class TestBatchFile:
    def test_each_line_marks_the_text_before_the_point(self, tmp_path):
        lines = _batch_file(tmp_path, _config(WITH_POINT))

        assert [_marked_texts(line) for line in lines] == [[SHARED], [SHARED]]
        for line in lines:
            TypeAdapter(Request).validate_python(line)
            for block in line["params"]["messages"][0]["content"]:
                TypeAdapter(TextBlockParam).validate_python(block, strict=True)

    def test_two_records_of_one_page_mark_the_same_block_and_differ_after_it(self, tmp_path):
        first, second = (
            line["params"]["messages"][0]["content"]
            for line in _batch_file(tmp_path, _config(WITH_POINT))
        )

        assert json.dumps(first[0]).encode() == json.dumps(second[0]).encode()
        assert first[0] == {"type": "text", "text": SHARED, "cache_control": MARK}
        assert first[1] != second[1]
        assert "cache_control" not in first[1]

    def test_each_line_carries_the_messages_the_online_request_carries(self, tmp_path):
        for caching in (True, False):
            lines = _batch_file(tmp_path / str(caching), _config(WITH_POINT, caching=caching))

            assert [line["params"]["messages"] for line in lines] == [
                _online(_config(WITH_POINT, caching=caching), record)["messages"]
                for record in RECORDS
            ]

    def test_with_caching_off_the_file_is_the_one_written_without_the_tag(self, tmp_path):
        marked = _batch_file(tmp_path / "marked", _config(WITH_POINT, caching=False))
        plain = _batch_file(tmp_path / "plain", _config(WITHOUT_POINT, caching=False))

        assert marked == plain
        assert "cache_control" not in json.dumps(marked)

    def test_the_model_reads_the_text_it_reads_without_the_tag(self, tmp_path):
        marked = _batch_file(tmp_path / "marked", _config(WITH_POINT))
        plain = _batch_file(tmp_path / "plain", _config(WITHOUT_POINT, caching=False))

        assert [_joined(line["params"]["messages"][0]["content"]) for line in marked] == [
            line["params"]["messages"][0]["content"] for line in plain
        ]

    def test_a_repair_round_marks_the_block_the_first_round_marked(self, tmp_path):
        feedback = {record["target_id"]: "The summary is empty." for record in RECORDS}
        lines = _batch_file(tmp_path, _config(WITH_POINT), feedback=feedback)

        assert [_marked_texts(line) for line in lines] == [[SHARED], [SHARED]]
        assert all(
            "The summary is empty." in _joined(line["params"]["messages"][0]["content"])
            for line in lines
        )


class TestAVendorWithoutCacheMarks:
    def test_an_openai_request_is_byte_for_byte_the_one_sent_without_the_tag(self):
        for caching in (True, False):
            (marked,) = _online_bytes(
                _config(WITH_POINT, vendor="openai", caching=caching), RECORDS[0]
            )
            (plain,) = _online_bytes(
                _config(WITHOUT_POINT, vendor="openai", caching=caching), RECORDS[0]
            )

            assert marked == plain

    def test_an_openai_batch_line_is_the_one_written_without_the_tag(self, tmp_path):
        client = OpenAIBatchClient(api_key="sk-test")
        marked = _batch_tasks(tmp_path, _config(WITH_POINT, vendor="openai"), client)
        plain = _batch_tasks(tmp_path, _config(WITHOUT_POINT, vendor="openai"), client)

        assert json.dumps(marked) == json.dumps(plain)

    @pytest.mark.parametrize("provider", sorted(PROVIDER_MESSAGE_CONFIGS))
    @pytest.mark.parametrize("json_mode", [True, False], ids=["json", "text"])
    def test_every_vendor_is_sent_the_text_whatever_the_cache_points(self, provider, json_mode):
        prompt = f"## PAGE\n{PAGE}\n## THE SLOT\nIt rained.\n"
        points = (len(f"## PAGE\n{PAGE}\n"),)
        plain = MessageBuilder.build(provider, prompt, {"a": 1}, json_mode=json_mode)
        marked = MessageBuilder.build(
            provider, prompt, {"a": 1}, json_mode=json_mode, cache_points=points
        )

        assert marked.to_dicts() == plain.to_dicts()
        assert marked.prompt_body == plain.prompt_body
        assert ["".join(text for text, _ in m.segments()) for m in marked.messages] == [
            m.content for m in plain.messages
        ]


class TestWhichCallsMarkThePoints:
    def test_a_call_whose_request_varies_per_record_marks_none(self):
        assert cache_points_of({CACHE_POINTS_KEY: (3,)}) == (3,)
        assert cache_points_of({CACHE_POINTS_KEY: (3,), REQUEST_VARIES_PER_RECORD_KEY: True}) == ()
        assert cache_points_of({}) == ()

    def test_a_repair_prompt_that_does_not_begin_with_the_prompt_marks_none(self):
        repair = {"prompt": "Fix this.\n\n{original_prompt}\n\n{failed_lines}"}
        first, second = (
            json.loads(body)
            for body in _online_bytes(_config(WITH_POINT), RECORDS[0], repair=repair)  # type: ignore[arg-type]
        )

        assert _marked_texts(first) == [SHARED]
        assert _marked_texts(second) == []

    @pytest.mark.parametrize("points", [(5, 3), (99,)], ids=["descending", "past-the-prompt"])
    def test_points_outside_the_prompt_are_refused(self, points):
        with pytest.raises(ValueError, match="must ascend within the shared prompt"):
            MessageBuilder.build("anthropic", "A prompt.", "{}", cache_points=points)

    def test_a_point_past_the_shared_part_of_a_repair_prompt_is_refused(self):
        with pytest.raises(ValueError, match="must ascend within the shared prompt"):
            MessageBuilder.build(
                "anthropic", "A prompt. Feedback.", "{}", shared_prompt_len=9, cache_points=(12,)
            )

    def test_a_point_with_no_text_since_the_last_one_places_no_blank_block(self):
        envelope = MessageBuilder.build("anthropic", "ab", "{}", cache_points=(1, 1, 2, 2))

        blocks = message_params(envelope)[0]["content"]
        assert [block["text"] for block in blocks[:2]] == [
            "\n<|begin_of_user_instruction|>: a",
            "b",
        ]
        assert all(block["text"].strip() for block in blocks)

    def test_more_boundaries_than_a_request_takes_are_refused_not_dropped(self):
        content = "a b c d e f"
        message = LLMMessage(
            role="user", content=content, static_len=len(content), cache_boundaries=(2, 4, 6, 8, 10)
        )

        with pytest.raises(ValueError, match="at most 4 cache breakpoints"):
            message_params(LLMMessageEnvelope(messages=[message]))
