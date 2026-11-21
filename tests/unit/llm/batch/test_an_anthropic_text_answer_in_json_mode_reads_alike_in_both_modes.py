"""An Anthropic JSON action whose model answers in text is read the same way in both modes.

Offered the schema tool, or given no schema at all, the model can answer in text. Online
reads an object or a list of objects out of that text and refuses anything else as a parse
error. Batch took whatever the lenient parser found: `["a", "b"]` became two `{value: ...}`
records, `42` one, and `null` an empty answer.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.llm.providers import client_base
from agent_actions.processing.helpers import get_parse_error_marker

from .one_answer_both_ways import action_config, batch, online, without_the_reason

TOOL = [{"name": "tag_page", "description": "", "input_schema": {"type": "object"}}]

REFUSED = {
    "a-list-of-strings": '["a", "b"]',
    "a-list-of-numbers": "[1, 2, 3]",
    "prose-quoting-a-list": "Here is a list: [1, 2, 3] done",
    "a-list-mixing-objects-and-strings": '[{"tag": "a"}, "b"]',
    "an-empty-list": "[]",
    "a-number": "42",
    "null": "null",
    "prose": "The page is about tides.",
}
READ = {
    "an-object": '{"tag": "a"}',
    "a-fenced-object": '```json\n{"tag": "a"}\n```',
    "a-list-of-objects": '[{"tag": "a"}, {"tag": "b"}]',
}
SCHEMAS = pytest.mark.parametrize("schema", [TOOL, None], ids=["tool-offered", "no-schema"])


@pytest.fixture(autouse=True)
def _no_cached_sdk_client(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})


def _both(text: str, schema: Any, tmp_path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = action_config(json_mode=True)
    return batch("anthropic", text, config, tmp_path), online("anthropic", text, config, schema)


@SCHEMAS
@pytest.mark.parametrize("text", REFUSED.values(), ids=REFUSED.keys())
def test_text_that_is_no_object_is_a_parse_error_holding_the_text(text, schema, tmp_path):
    in_batch, in_online = _both(text, schema, tmp_path)

    # Each mode words the parse error its own way.
    assert without_the_reason(in_batch) == without_the_reason(in_online)
    assert [record["raw_response"] for record in in_batch] == [text]
    assert get_parse_error_marker(in_batch)


@SCHEMAS
@pytest.mark.parametrize("text", READ.values(), ids=READ.keys())
def test_an_object_or_a_list_of_objects_in_text_is_the_answer(text, schema, tmp_path):
    in_batch, in_online = _both(text, schema, tmp_path)

    assert in_batch == in_online
    assert not get_parse_error_marker(in_batch)
