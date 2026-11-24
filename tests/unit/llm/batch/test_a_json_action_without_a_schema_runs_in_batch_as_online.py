"""A JSON action with no schema runs in batch, and asks for JSON as its online call does.

Online runs such an action: OpenAI and Groq are sent `response_format: {type: json_object}`,
Gemini a JSON mime type, and Anthropic no tool, its text read as JSON. Batch submission
refused the action with "Schema is required for batch processing when json_mode is enabled".
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.anthropic.client import AnthropicClient
from agent_actions.llm.providers.gemini.client import GeminiClient
from agent_actions.llm.providers.groq.client import GroqClient
from agent_actions.llm.providers.openai.client import OpenAIClient
from agent_actions.processing.prepared_task import GuardStatus

from .one_answer_both_ways import USAGE, VENDORS, action_config, batch, batch_client, online

ROW = {"target_id": "r1", "content": {"t": "x"}, "prompt": "p"}
SCHEMA = {"name": "tags", "schema": {"type": "object", "properties": {"tag": {"type": "string"}}}}
JSON_OBJECT = {"type": "json_object"}
OPENAI_SHAPED = {
    "openai": ("agent_actions.llm.providers.openai.client.OpenAI", OpenAIClient),
    "groq": ("agent_actions.llm.providers.groq.client.Groq", GroqClient),
}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})
    with patch(USAGE):
        yield


def _config(vendor: str, **settings: Any) -> dict[str, Any]:
    return action_config(model_vendor=vendor, **settings)


def _batch_line(vendor: str, config: dict[str, Any]) -> dict[str, Any]:
    (task,) = batch_client(vendor).prepare_tasks([dict(ROW)], config)
    return task  # type: ignore[no-any-return]


def _online_chat_request(
    vendor: str, config: dict[str, Any], schema: Any = None
) -> dict[str, Any]:
    path, client = OPENAI_SHAPED[vendor]
    with patch(path) as sdk:
        choice = MagicMock(finish_reason="stop")
        choice.message.content = "{}"
        choice.message.refusal = None
        create = sdk.return_value.chat.completions.create
        create.return_value = MagicMock(choices=[choice])
        if config.get("json_mode", True):
            client.call_json("k", config, "p", {"t": "x"}, schema)
        else:
            client.call_non_json("k", config, "p", {"t": "x"})
    return create.call_args.kwargs  # type: ignore[no-any-return]


@pytest.mark.parametrize("vendor", VENDORS)
def test_batch_submission_prepares_the_action(vendor):
    prepared = MagicMock(
        guard_status=GuardStatus.PASSED,
        passthrough_fields={},
        llm_context={"t": "x"},
        formatted_prompt="p",
    )
    preparer = MagicMock()
    preparer.prepare.return_value = prepared
    with (
        patch(
            "agent_actions.llm.batch.processing.preparator.get_task_preparer",
            return_value=preparer,
        ),
        patch("agent_actions.prompt.formatter.PromptFormatter.get_raw_prompt"),
        patch.object(BatchTaskPreparator, "_run_preflight_validation"),
    ):
        tasks = BatchTaskPreparator().prepare_tasks(
            _config(vendor, json_mode=True),
            [{"target_id": "r1", "source_guid": "g1", "content": {"t": "x"}}],
            batch_client(vendor),
        )

    assert len(tasks.tasks) == 1


@pytest.mark.parametrize("vendor", OPENAI_SHAPED)
class TestAnOpenAIShapedRequest:
    def test_it_asks_for_a_json_object_as_online_does(self, vendor):
        config = _config(vendor, json_mode=True)

        asked = _batch_line(vendor, config)["body"].get("response_format")

        assert asked == JSON_OBJECT
        assert asked == _online_chat_request(vendor, config)["response_format"]

    def test_a_schema_is_still_sent_as_the_schema(self, vendor):
        config = _config(vendor, json_mode=True)

        asked = _batch_line(vendor, {**config, "compiled_schema": SCHEMA})["body"]

        assert asked["response_format"] == {"type": "json_schema", "json_schema": SCHEMA}
        assert (
            asked["response_format"]
            == _online_chat_request(vendor, config, SCHEMA)["response_format"]
        )

    def test_a_text_action_asks_for_no_format_in_either_mode(self, vendor):
        config = _config(vendor, json_mode=False)

        assert "response_format" not in _batch_line(vendor, config)["body"]
        assert "response_format" not in _online_chat_request(vendor, config)


def test_anthropic_offers_no_tool_in_either_mode():
    config = _config("anthropic", json_mode=True)
    with patch("anthropic.Anthropic") as sdk:
        sdk.return_value.messages.create.return_value = MagicMock(
            content=[], stop_reason="end_turn"
        )
        AnthropicClient.call_json("k", config, "p", {"t": "x"}, None)

    assert "tools" not in sdk.return_value.messages.create.call_args.kwargs
    assert "tools" not in _batch_line("anthropic", config)["params"]


def test_gemini_asks_for_json_in_both_modes():
    config = _config("gemini", json_mode=True)
    with patch("agent_actions.llm.providers.gemini.client._build_client") as build:
        generate = build.return_value.models.generate_content
        generate.return_value = MagicMock(text="{}", candidates=[])
        GeminiClient.call_json("k", config, "p", {"t": "x"}, None)

    online_mime = generate.call_args.kwargs["config"].response_mime_type
    batch_mime = _batch_line("gemini", config)["request"]["generation_config"][
        "response_mime_type"
    ]
    assert batch_mime == online_mime == "application/json"


ANSWERS = {
    "an-object": '{"tag": "a"}',
    "a-fenced-object": '```json\n{"tag": "a"}\n```',
    "a-list-of-objects": '[{"tag": "a"}, {"tag": "b"}]',
}


@pytest.mark.parametrize("vendor", VENDORS)
@pytest.mark.parametrize("text", ANSWERS.values(), ids=ANSWERS.keys())
def test_the_answer_is_stored_as_online_stores_it(vendor, text, tmp_path):
    config = _config(vendor, json_mode=True)

    assert batch(vendor, text, config, tmp_path) == online(vendor, text, config)
