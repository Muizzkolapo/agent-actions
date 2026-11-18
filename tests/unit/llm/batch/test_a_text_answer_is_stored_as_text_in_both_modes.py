"""With `json_mode: false`, a batch action stores the model's reply as text, as online does.

Batch read every reply with the lenient JSON parser whatever the action's mode, so prose that
quoted a list or an object was stored as that list or object: three `{value: n}` records for
"Here is a list: [1, 2, 3] done", where online stores one record holding the sentence.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.expectations.service import create_expectation_service_from_config
from agent_actions.llm.batch.services.retry_serialization import (
    deserialize_results,
    serialize_results,
)
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.evaluation.strategies.expectations import ExpectationStrategy

from .one_answer_both_ways import (
    ACTION,
    VENDORS,
    action_config,
    batch,
    batch_client,
    online,
    online_answer,
)

ANSWERS = {
    "prose-with-a-list": "Here is a list: [1, 2, 3] done",
    "prose-with-an-object": 'Summary: the user said {"a": 1}.',
    "an-object": '{"a": 1}',
    "a-fenced-object": '```json\n{"a": 1}\n```',
    "a-list-of-objects": '[{"a": 1}, {"a": 2}]',
    "a-number": "42",
    "prose": "The page is about tides.",
}


@pytest.fixture(autouse=True)
def _no_cached_sdk_client(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})


@pytest.mark.parametrize("vendor", VENDORS)
@pytest.mark.parametrize("text", ANSWERS.values(), ids=ANSWERS.keys())
def test_the_reply_is_stored_as_online_stores_it(vendor, text, tmp_path):
    config = action_config(json_mode=False)

    assert batch(vendor, text, config, tmp_path) == online(vendor, text, config)


@pytest.mark.parametrize("vendor", (*VENDORS, "agac"))
def test_the_reply_is_one_record_holding_the_text(vendor, tmp_path):
    text = ANSWERS["prose-with-a-list"]

    assert batch(vendor, text, action_config(json_mode=False), tmp_path) == [{"raw_response": text}]


@pytest.mark.parametrize("vendor", VENDORS)
def test_the_text_is_stored_under_the_action_s_output_field(vendor, tmp_path):
    config = action_config(json_mode=False, output_field="summary")
    text = ANSWERS["prose-with-an-object"]

    stored = batch(vendor, text, config, tmp_path)

    assert stored == [{"summary": text}]
    assert stored == online(vendor, text, config)


def test_a_json_action_still_reads_json_out_of_its_reply(tmp_path):
    stored = batch("openai", ANSWERS["a-fenced-object"], action_config(json_mode=True), tmp_path)

    assert stored == [{"a": 1}]


def _retrieved(text: str, config: dict[str, Any], tmp_path) -> BatchResult:
    """The result a collect pass holds for a reply, before any repair round reads it."""
    provider = batch_client("agac")
    line = {"custom_id": "r1", "response": {"body": {"choices": [{"message": {"content": text}}]}}}
    provider.retrieve_results = lambda batch_id, output_directory=None: [
        provider.parse_provider_response(line)
    ]
    (result,) = retrieve_and_reconcile(provider, "b1", str(tmp_path), agent_config=config)
    return result


def test_the_text_survives_the_wait_for_a_recovery_batch(tmp_path):
    """A retry or repair round stores the answers it has, and reads them back later."""
    text = ANSWERS["prose-with-a-list"]
    result = _retrieved(text, action_config(json_mode=False), tmp_path)

    (carried,) = deserialize_results(serialize_results([result]))

    assert carried.content == {"raw_response": text}


EXPECT = {
    "repair": "auto",
    "max_iterations": 1,
    "expectations": [
        {
            "id": "names_one_topic",
            "type": "accepted_values",
            "field": "raw_response",
            "params": {"values": ["tides", "moons"]},
        }
    ],
}


@pytest.mark.parametrize("text", ["tides", "[1, 2, 3]", "The page is about tides."])
def test_a_repair_loop_judges_the_reply_as_online_judges_it(text, tmp_path):
    """Online judges the record holding the text; batch failed every reply as not a record."""
    config = action_config(json_mode=False, expect=EXPECT)

    def service():
        return create_expectation_service_from_config(
            EXPECT, action_name=ACTION, agent_config=config
        )

    in_online = service().execute(lambda prompt: (online_answer("openai", text, config), True), "p")
    in_batch = ExpectationStrategy(service()).evaluate(_retrieved(text, config, tmp_path))

    assert in_batch.passed == in_online.suite_result.overall_pass == (text == "tides")
