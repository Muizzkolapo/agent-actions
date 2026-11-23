"""No Anthropic repair request carries a blank text block, and a repair keeps a per-record schema
unmarked."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.expectations.service import ExpectationService
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.providers.anthropic import message_params
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.processing.invocation.online import OnlineStrategy
from agent_actions.processing.prepared_task import PreparedTask
from agent_actions.prompt.message_builder import LLMMessage, MessageBuilder
from agent_actions.prompt.service import PromptPreparationService
from tests.unit.llm.providers import (
    test_anthropic_marks_only_a_prompt_every_record_shares as dispatch,
)
from tests.unit.llm.providers import (
    test_anthropic_repair_reads_the_first_calls_cache_entry as repair,
)

MARK = {"type": "ephemeral"}
STATIC = repair.STATIC
FEEDBACK = repair.FEEDBACK
PAGES = repair.PAGES


def _blank_blocks(value: Any) -> list[Any]:
    """Every text block whose text is empty or only whitespace, anywhere in *value*."""
    if isinstance(value, dict):
        own = (
            [value]
            if value.get("type") == "text" and not str(value.get("text", "")).strip()
            else []
        )
        return own + [b for v in value.values() for b in _blank_blocks(v)]
    if isinstance(value, list):
        return [b for v in value for b in _blank_blocks(v)]
    return []


def _batch(
    tmp_path: Path, config: dict[str, Any], feedback: dict[str, str] | None, attempt: int
) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    client = AnthropicBatchClient(
        api_key="sk-ant-test", enable_prompt_caching=config["enable_prompt_caching"]
    )
    client.client = repair._sdk_client("anthropic", sent)
    data = [
        {"target_id": page, "source_guid": f"sg-{page}", "content": {"page_content": page}}
        for page in PAGES
    ]
    tasks = (
        BatchTaskPreparator(action_indices={}, dependency_configs={}, storage_backend=MagicMock())
        .prepare_tasks(
            agent_config=config,
            data=data,
            provider=client,
            output_directory=str(tmp_path),
            attempt=attempt,
            feedback_by_id=feedback,
        )
        .tasks
    )
    client.submit_batch(tasks, "pages", str(tmp_path))
    (body,) = sent
    return [line["params"] for line in body["requests"]]


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "sk-test")
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "sk-ant-test")


class TestEmptyFeedback:
    @pytest.mark.parametrize("empty", ["", "  \n"], ids=["empty", "whitespace"])
    def test_a_round_with_no_feedback_sends_the_first_rounds_marked_prompt(self, tmp_path, empty):
        config = repair._config(STATIC)
        params = _batch(tmp_path, config, {page: empty for page in PAGES}, 1)

        assert [repair._marked_texts(p) for p in params] == [[repair.SHARED]] * 2
        assert [p["messages"] for p in params] == [
            p["messages"] for p in _batch(tmp_path, config, None, 0)
        ]

    def test_a_round_with_no_feedback_sends_the_prompt_untouched_with_caching_off(self, tmp_path):
        config = repair._config(STATIC, caching=False)
        params = _batch(tmp_path, config, {page: "" for page in PAGES}, 1)

        assert [p["messages"] for p in params] == [
            p["messages"] for p in _batch(tmp_path, config, None, 0)
        ]
        assert [
            p["messages"][0]["content"].startswith(f"{repair.SHARED} :<|end_of") for p in params
        ] == [True, True]


class TestNoBlankBlock:
    @pytest.mark.parametrize(
        "feedback",
        [
            None,
            {page: FEEDBACK for page in PAGES},
            {page: "" for page in PAGES},
            {page: "  \n" for page in PAGES},
        ],
        ids=["first-round", "feedback", "empty-feedback", "whitespace-feedback"],
    )
    @pytest.mark.parametrize("prompt", [STATIC, repair.TEMPLATED], ids=["static", "templated"])
    def test_no_batch_request_carries_a_blank_text_block(self, tmp_path, feedback, prompt):
        params = _batch(tmp_path, repair._config(prompt), feedback, 1 if feedback else 0)

        assert len(params) == 2
        assert _blank_blocks(params) == []

    @pytest.mark.parametrize(
        ("prompt", "mode"),
        [
            (STATIC, "auto"),
            (repair.TEMPLATED, "auto"),
            (STATIC, {"prompt": "{original_prompt}\n\n"}),
            (STATIC, {"prompt": "Fix this.\n\n{original_prompt}\n\n{failed_lines}"}),
        ],
        ids=["static", "templated", "template-adds-only-whitespace", "template-before-prompt"],
    )
    def test_no_online_request_carries_a_blank_text_block(self, prompt, mode):
        bodies = repair._online(repair._config(prompt), repair=mode)

        assert len(bodies) == 2
        assert _blank_blocks(bodies) == []

    def test_the_builder_sends_no_blank_block(self):
        blank_tail = MessageBuilder.build(
            "anthropic",
            f"{STATIC}\n\n",
            "{}",
            enable_prompt_caching=True,
            shared_prompt_len=len(STATIC),
        )
        blank_prompt = MessageBuilder.build("anthropic", "   ", "{}", enable_prompt_caching=True)
        shared = MessageBuilder.build("anthropic", STATIC, "{}", enable_prompt_caching=True)

        for envelope in (blank_tail, blank_prompt, shared):
            assert _blank_blocks(message_params(envelope)) == []
        assert repair._marked_texts(message_params(shared)) == [repair.SHARED]

    def test_the_marking_rule_marks_no_part_that_would_leave_a_blank_block(self):
        blank_tail = [LLMMessage(role="system", content=f"{STATIC}\n\n", static_len=len(STATIC))]
        blank_prompt = [LLMMessage(role="system", content="   ", static_len=3)]

        for messages in (blank_tail, blank_prompt):
            placed = MessageBuilder._place_cache_boundaries(
                messages, (), messages[0].static_len, at_prompt_end=True
            )
            assert placed == messages

    def test_the_blank_block_search_finds_a_blank_block(self):
        assert _blank_blocks(
            {"system": [{"type": "text", "text": "x"}, {"type": "text", "text": "\n\n"}]}
        ) == [{"type": "text", "text": "\n\n"}]


class TestLaterRounds:
    def test_a_second_repair_round_marks_the_first_rounds_block(self, tmp_path):
        params = _batch(tmp_path, repair._config(STATIC), {page: FEEDBACK for page in PAGES}, 2)

        for request in params:
            marked, rest = request["messages"][0]["content"]
            assert marked == {"type": "text", "text": repair.SHARED, "cache_control": MARK}
            assert rest["text"].startswith(f"\n\n{FEEDBACK} :<|end_of_user_instruction|>")


def _online_dispatched(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Send one record of a per-record-schema action through the repair loop; return both
    bodies."""
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
        expectation_service=ExpectationService(repair.SUITE, repair="auto", max_iterations=2)
    )
    with patch(
        "agent_actions.llm.providers.client_base.get_or_create_client",
        lambda *_a, **_k: dispatch._sdk(sent),
    ):
        strategy.invoke(task, context)
    return sent


class TestDispatchedSchemaRepair:
    def test_a_repair_of_an_action_whose_record_chooses_its_schema_carries_no_mark(self, tmp_path):
        config = dispatch._config(STATIC, **dispatch._dispatch_project(tmp_path))
        bodies = _online_dispatched(config)

        assert len(bodies) == 2
        first, second = bodies
        assert [b["tools"][0]["name"] for b in bodies] == ["topic_answer"] * 2
        assert repair.FEEDBACK_START in repair._joined(second["messages"][0]["content"])
        assert repair.FEEDBACK_START not in repair._joined(first["messages"][0]["content"])
        assert [repair._marked_texts(first), repair._marked_texts(second)] == [[], []]
