"""A response's tokens are counted the same online and in batch.

Batch counted an Anthropic result's `input_tokens` alone, where online adds the tokens read
from and written to the prompt cache, so a cached batch reported fewer prompt tokens than
the same calls made online.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.llm.batch.services.processing_recovery import report_batch_usage
from agent_actions.llm.providers.usage_tracker import clear_usage, get_last_usage
from agent_actions.processing.run_counts import counting
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

RESPONSES: dict[str, dict[str, Any]] = {
    "openai": chat_completion(ANSWER),
    "groq": chat_completion(ANSWER),
    "gemini": gemini_response([{"text": ANSWER}]),
    "anthropic": anthropic_message([{"type": "text", "text": ANSWER}], usage=CACHED_USAGE),
    "ollama_local": ollama_response(ANSWER),
}


def _online_tokens(vendor: str) -> dict[str, int] | None:
    clear_usage()
    online_answer(vendor, RESPONSES[vendor], json_mode=True)
    return get_last_usage()


def _batch_tokens(vendor: str) -> dict[str, int] | None:
    with counting() as counts:
        report_batch_usage([batch_line(vendor, RESPONSES[vendor])])
    return counts.tokens


@pytest.mark.parametrize("vendor", sorted(RESPONSES))
def test_a_response_counts_the_same_tokens_in_both_modes(vendor):
    assert _batch_tokens(vendor) == _online_tokens(vendor)


def test_an_anthropic_batch_result_counts_its_cached_prompt_tokens():
    assert _batch_tokens("anthropic") == {
        "input_tokens": 127,
        "output_tokens": 3,
        "total_tokens": 130,
    }


def test_a_gemini_batch_result_counts_its_thinking_tokens_as_output():
    assert _batch_tokens("gemini") == {"input_tokens": 7, "output_tokens": 8, "total_tokens": 15}


def test_a_result_with_no_usage_counts_nothing():
    with counting() as counts:
        report_batch_usage([batch_line("openai", {**RESPONSES["openai"], "usage": None})])

    assert counts.tokens is None
