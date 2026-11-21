"""A JSON answer that a stop not of the model's own ended is a parse error, online and in batch.

A content filter, a safety or recitation block, or an Anthropic refusal can stop an answer
partway. Every client then completed the partial JSON into an object and stored it as a
success: `{"a": "x", "b": "tru` became `{"a": "x", "b": "tru"}`.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.llm.batch.one_answer_both_paths import (
    End,
    anthropic_message,
    batch_end,
    chat_completion,
    gemini_response,
    online_end,
)

PARTIAL = '{"a": "x", "b": "tru'

# case: vendor, response body, the stop reason the parse error names
STOPPED: dict[str, tuple[str, dict[str, Any], str]] = {
    "openai content filter": (
        "openai",
        chat_completion(PARTIAL, "content_filter"),
        "content_filter",
    ),
    "gemini safety": ("gemini", gemini_response([{"text": PARTIAL}], "SAFETY"), "SAFETY"),
    "gemini recitation": (
        "gemini",
        gemini_response([{"text": PARTIAL}], "RECITATION"),
        "RECITATION",
    ),
    "anthropic refusal": (
        "anthropic",
        anthropic_message([{"type": "text", "text": PARTIAL}], "refusal"),
        "refusal",
    ),
}


def _expected(reason: str) -> End:
    return End(
        stored=[
            {
                "raw_response": PARTIAL,
                "_parse_error": f"The provider stopped the answer before its end "
                f"(stop_reason={reason}); the answer is not complete",
            }
        ]
    )


@pytest.mark.parametrize("path", [online_end, batch_end], ids=["online", "batch"])
@pytest.mark.parametrize("case", sorted(STOPPED))
def test_it_is_a_parse_error_naming_the_stop_reason(case, path):
    vendor, body, reason = STOPPED[case]

    assert path(vendor, body, json_mode=True) == _expected(reason)


@pytest.mark.parametrize("vendor", ["openai", "gemini", "anthropic"])
def test_an_answer_the_model_finished_is_still_read_as_json(vendor):
    body = {
        "openai": chat_completion('{"a": "x"}'),
        "gemini": gemini_response([{"text": '{"a": "x"}'}]),
        "anthropic": anthropic_message([{"type": "text", "text": '{"a": "x"}'}]),
    }[vendor]

    assert online_end(vendor, body, json_mode=True) == End(stored=[{"a": "x"}])
    assert batch_end(vendor, body, json_mode=True) == End(stored=[{"a": "x"}])
