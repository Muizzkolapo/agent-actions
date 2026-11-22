"""An Anthropic action with `json_mode: false`, an `output_field` and a schema, in batch.

Online sends such an action no tool and stores the first text block under its output
field. Batch must ask the same thing and store the same record, so a rule on that field,
an `llm_judge` among them, reads the answer text.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.anthropic.client import AnthropicClient
from agent_actions.llm.providers.batch_base import BatchResult

from .judge_batch_world import JudgingProvider, Run, judged_config, verdict
from .one_answer_both_ways import ACTION, ROW, USAGE, action_config, batch_client
from .one_answer_both_ways import online as online_record

SCHEMA = [
    {
        "name": "compact_write_text",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {"raw": {"type": "string"}},
            "required": ["raw"],
            "additionalProperties": True,
        },
    }
]
JSON_TEXT = json.dumps({"raw": "One question.", "questions": [{"q": "Which?", "a": "B"}]})
TOOL_INPUT = {"raw": "A one-line summary.", "questions": [{"q": "Which?", "a": "B"}]}


def _config() -> dict[str, Any]:
    return action_config(json_mode=False, output_field="raw")


@pytest.fixture(autouse=True)
def _no_cached_sdk_client(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})


def _line(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "custom_id": "r1",
        "result": {
            "type": "succeeded",
            "message": {
                "model": "m",
                "role": "assistant",
                "content": blocks,
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        },
    }


def _retrieved(blocks: list[dict[str, Any]], config: dict[str, Any], tmp_path) -> BatchResult:
    """The collect pass's result for an Anthropic batch whose one line holds *blocks*."""
    provider = batch_client("anthropic")
    provider._fetch_raw_results = lambda batch_id: (json.dumps(_line(blocks)) + "\n").encode()
    (result,) = retrieve_and_reconcile(
        provider, "b1", str(tmp_path), context_map={"r1": dict(ROW)}, agent_config=config
    )
    return result


def _stored_in_batch(blocks: list[dict[str, Any]], tmp_path) -> list[dict[str, Any]]:
    config = _config()
    result = _retrieved(blocks, config, tmp_path)
    context_map = {"r1": dict(ROW)}
    (processed,) = BatchResultStrategy().process(
        [result], context_map=context_map, agent_config=config
    )
    return [record["content"][ACTION] for record in processed.data]


def _online_api_args(blocks: list[SimpleNamespace]) -> tuple[list[Any], dict[str, Any]]:
    """What online returns for *blocks*, and the arguments it sent the API."""
    with patch("anthropic.Anthropic") as sdk, patch(USAGE):
        create = sdk.return_value.messages.create
        create.return_value = MagicMock(content=blocks, stop_reason="end_turn")
        answer = AnthropicClient.call_non_json("k", _config(), "p", {"t": "x"})
    return answer, create.call_args.kwargs


def test_the_batch_line_offers_no_tool_as_online_sends_none():
    provider = batch_client("anthropic")
    row = {"target_id": "r1", "prompt": "Write.", "content": {"source": {"page": "p1"}}}

    (task,) = provider.prepare_tasks([row], {**_config(), "compiled_schema": SCHEMA})
    _, online_args = _online_api_args([SimpleNamespace(type="text", text="x")])

    assert "tools" not in task["params"]
    assert "tools" not in online_args


def test_a_text_answer_holding_json_is_stored_whole_under_the_output_field(tmp_path):
    stored = _stored_in_batch([{"type": "text", "text": JSON_TEXT}], tmp_path)

    assert stored == [{"raw": JSON_TEXT}]
    assert stored == online_record("anthropic", JSON_TEXT, _config())


def test_a_tool_answer_beside_the_text_is_stored_as_the_text_alone(tmp_path):
    blocks = [
        {"type": "text", "text": JSON_TEXT},
        {"type": "tool_use", "id": "t1", "name": "compact_write_text", "input": TOOL_INPUT},
    ]
    online_answer, _ = _online_api_args(
        [
            SimpleNamespace(type="text", text=JSON_TEXT),
            SimpleNamespace(type="tool_use", id="t1", name="compact_write_text", input=TOOL_INPUT),
        ]
    )

    assert online_answer == [{"raw": JSON_TEXT}]
    assert _stored_in_batch(blocks, tmp_path) == online_answer


def test_a_tool_answer_with_no_text_fails_the_record_as_online_raises(tmp_path):
    blocks = [{"type": "tool_use", "id": "t1", "name": "compact_write_text", "input": TOOL_INPUT}]
    with pytest.raises(Exception) as online_error:
        _online_api_args(
            [SimpleNamespace(type="tool_use", id="t1", name="compact_write_text", input=TOOL_INPUT)]
        )

    result = _retrieved(blocks, _config(), tmp_path)

    assert result.content is None
    assert result.error == str(online_error.value)


def test_an_llm_judge_on_the_output_field_reads_the_answer_text(tmp_path):
    rule = {
        "id": "no_stem_leak",
        "type": "llm_judge",
        "field": "raw",
        "params": {"rule": "The questions do not leak the stem.", "votes": 1},
    }
    config = {**judged_config([rule], repair="none"), "output_field": "raw"}
    seen: list[Any] = []

    def reply(prompt: str, vote: int) -> str:
        # A string value is put in the judge prompt as it is, not as JSON.
        seen.append(re.search(r"## Value under test\n(.*)\n\nRespond with ONLY", prompt, re.S)[1])
        return verdict(True)

    result = _retrieved([{"type": "text", "text": JSON_TEXT}], config, tmp_path)
    result.custom_id = "r1"
    run = Run(config, JudgingProvider(reply))
    run.main_batch_returns([result])
    run.recovery_batch_returns()

    assert seen == [JSON_TEXT]
