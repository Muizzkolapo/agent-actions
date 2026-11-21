"""A response's tokens are counted the same online and in batch, in the same four fields.

Each vendor reports usage in its own shape. `ResponseBuilder` reads every shape into one:
the prompt tokens neither read from nor written to the cache, the output tokens, and the
tokens read from and written to the cache. A vendor that reports no cached tokens gives 0.
The online client and the batch client of one vendor count one response alike.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.llm.batch.services.shared import count_batch_usage
from agent_actions.llm.providers.usage_tracker import UsageLedger, accounting
from tests.unit.llm.batch.one_answer_both_paths import (
    anthropic_message,
    batch_line,
    chat_completion,
    gemini_response,
    ollama_response,
    online_answer,
)

ANSWER = '{"topic": "tides"}'
CACHED_USAGE = {
    "input_tokens": 7,
    "output_tokens": 3,
    "cache_read_input_tokens": 100,
    "cache_creation_input_tokens": 20,
}


def _chat_completion_reading_the_cache() -> dict[str, Any]:
    body = chat_completion(ANSWER)
    body["usage"] = {
        "prompt_tokens": 107,
        "completion_tokens": 3,
        "total_tokens": 110,
        "prompt_tokens_details": {"cached_tokens": 100},
    }
    return body


def _gemini_response_reading_the_cache() -> dict[str, Any]:
    body = gemini_response([{"text": ANSWER}])
    body["usageMetadata"] = {
        "promptTokenCount": 107,
        "candidatesTokenCount": 3,
        "totalTokenCount": 110,
        "cachedContentTokenCount": 100,
    }
    return body


RESPONSES: dict[str, dict[str, Any]] = {
    "openai": chat_completion(ANSWER),
    "groq": chat_completion(ANSWER),
    "gemini": gemini_response([{"text": ANSWER}]),
    "anthropic": anthropic_message([{"type": "text", "text": ANSWER}], usage=CACHED_USAGE),
    "ollama_local": ollama_response(ANSWER),
}
READING_THE_CACHE: dict[str, dict[str, Any]] = {
    "openai": _chat_completion_reading_the_cache(),
    "gemini": _gemini_response_reading_the_cache(),
}


def _counted(ledger: UsageLedger) -> dict[str, int]:
    (row,) = ledger.rows()
    return {key: row[key] for key in row if key not in ("kind", "batch", "model")}


def _online(vendor: str, body: dict[str, Any]) -> dict[str, int]:
    ledger = UsageLedger("act")
    with accounting(ledger):
        online_answer(vendor, body, json_mode=True)
    return _counted(ledger)


def _batch(vendor: str, body: dict[str, Any]) -> dict[str, int]:
    ledger = UsageLedger("act")
    with accounting(ledger):
        count_batch_usage("batch-1", [batch_line(vendor, body)], kind="main", model="m")
    return _counted(ledger)


def _usage(calls: int, input_tokens: int, output_tokens: int, read: int = 0, written: int = 0):
    return {
        "calls": calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": read,
        "cache_creation_input_tokens": written,
    }


@pytest.mark.parametrize("vendor", sorted(RESPONSES))
def test_a_response_counts_the_same_tokens_in_both_modes(vendor):
    assert _batch(vendor, RESPONSES[vendor]) == _online(vendor, RESPONSES[vendor])


@pytest.mark.parametrize("vendor", sorted(READING_THE_CACHE))
def test_a_response_that_read_the_cache_counts_the_same_in_both_modes(vendor):
    assert _batch(vendor, READING_THE_CACHE[vendor]) == _online(vendor, READING_THE_CACHE[vendor])


def test_an_anthropic_response_counts_its_cached_prompt_tokens_apart_from_its_input():
    assert _batch("anthropic", RESPONSES["anthropic"]) == _usage(1, 7, 3, read=100, written=20)


@pytest.mark.parametrize("vendor", sorted(READING_THE_CACHE))
def test_the_cached_part_of_a_prompt_count_is_taken_out_of_the_input(vendor):
    """OpenAI and Gemini count the cached tokens inside the prompt count."""
    assert _online(vendor, READING_THE_CACHE[vendor]) == _usage(1, 7, 3, read=100)


@pytest.mark.parametrize("vendor", ["openai", "groq", "ollama_local"])
def test_a_vendor_that_reports_no_cached_tokens_counts_none(vendor):
    assert _online(vendor, RESPONSES[vendor]) == _usage(1, 7, 3)


def test_a_gemini_response_counts_its_thinking_tokens_as_output():
    assert _batch("gemini", RESPONSES["gemini"]) == _usage(1, 7, 8)


def test_an_answered_line_with_no_usage_is_a_call_with_no_tokens():
    line = batch_line("openai", {**RESPONSES["openai"], "usage": None})

    ledger = UsageLedger("act")
    with accounting(ledger):
        count_batch_usage("batch-1", [line], kind="main", model="m")

    assert _counted(ledger) == _usage(1, 0, 0)
