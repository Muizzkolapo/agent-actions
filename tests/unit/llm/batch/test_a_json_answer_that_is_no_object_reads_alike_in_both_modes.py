"""A JSON-mode reply that is not an object is stored the same way in batch as online.

Each vendor's online client has its own reading of such a reply. Ollama stores a list that
holds a non-object whole, under `response`, and refuses a bare number; batch split the list
into one `{value: item}` record per item and stored the number. A reply that is one JSON
string is a parse error in both modes, and batch kept its text without the quotes.
"""

from __future__ import annotations

import pytest

from agent_actions.llm.providers import client_base

from .one_answer_both_ways import VENDORS, action_config, batch, online, without_the_reason

ANSWERS = {
    "a-list-of-strings": '["a", "b"]',
    "a-list-of-numbers": "[1, 2, 3]",
    "a-list-mixing-objects-and-strings": '[{"tag": "a"}, "b"]',
    "a-list-of-lists": "[[1, 2], [3]]",
    "prose-quoting-a-list": "Here is a list: [1, 2, 3] done",
    "a-number": "42",
    "a-boolean": "true",
    "a-json-string": '"quoted"',
    "prose": "The page is about tides.",
    "an-object": '{"tag": "a"}',
    "a-list-of-objects": '[{"tag": "a"}, {"tag": "b"}]',
}


@pytest.fixture(autouse=True)
def _no_cached_sdk_client(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})


@pytest.mark.parametrize("vendor", VENDORS)
@pytest.mark.parametrize("text", ANSWERS.values(), ids=ANSWERS.keys())
def test_the_reply_is_stored_as_online_stores_it(vendor, text, tmp_path):
    config = action_config(json_mode=True)

    in_batch = batch(vendor, text, config, tmp_path)
    in_online = online(vendor, text, config)

    if vendor == "anthropic":
        # Its online client words a parse error its own way.
        in_batch, in_online = without_the_reason(in_batch), without_the_reason(in_online)
    assert in_batch == in_online


class TestOllama:
    def test_a_list_holding_a_non_object_is_one_record(self, tmp_path):
        stored = batch("ollama_local", '["a", "b"]', action_config(json_mode=True), tmp_path)

        assert stored == [{"response": ["a", "b"]}]

    def test_a_bare_number_is_a_parse_error_holding_the_text(self, tmp_path):
        (stored,) = batch("ollama_local", "42", action_config(json_mode=True), tmp_path)

        assert stored["raw_response"] == "42"
        assert stored["_parse_error"] == "Failed to parse JSON from LLM response"


@pytest.mark.parametrize("vendor", VENDORS)
def test_a_reply_that_is_one_json_string_keeps_its_text_as_written(vendor, tmp_path):
    (stored,) = batch(vendor, '"quoted"', action_config(json_mode=True), tmp_path)

    assert stored["raw_response"] == '"quoted"'
    assert "_parse_error" in stored
