"""A refused, blocked, empty or cut-off answer ends its record the same way online and in batch.

Each case is one vendor response read by the online client and by the batch client. A
refusal was resent by a batch `retry:` until it was exhausted; a Gemini answer with no
text failed in batch and was stored as an empty success online, and neither named the
block reason; an Anthropic message with no blocks went to `on_empty` in batch and raised
online; and a JSON answer the output limit cut off was completed into a partial object
by every client but Anthropic's.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from agent_actions.llm.providers.cohere.client import CohereClient
from tests.unit.llm.batch.one_answer_both_paths import (
    End,
    anthropic_message,
    batch_end,
    batch_line,
    chat_completion,
    gemini_response,
    ollama_response,
    online_end,
)

REFUSAL = "I can't help with that request."
REFUSED = f"The model refused to answer: {REFUSAL}"
CUT_OFF_JSON = '{"title": "Tides", "summary": "The moon pulls on the oce'
THINKING = {"type": "thinking", "thinking": "Let me work it out", "signature": "sig"}
THOUGHT = {"text": "Let me work it out", "thought": True}


def _parse_error(end: End) -> str:
    assert end.stored is not None, end
    (record,) = end.stored
    return str(record["_parse_error"])


# vendor, response body
NO_CONTENT: dict[str, tuple[str, dict[str, Any]]] = {
    "openai refusal": ("openai", chat_completion(None, refusal=REFUSAL)),
    "openai no content": ("openai", chat_completion(None)),
    "openai content filter": ("openai", chat_completion(None, "content_filter")),
    "openai cut off before any content": ("openai", chat_completion(None, "length")),
    "openai cut off at an empty string": ("openai", chat_completion("", "length")),
    "openai refusal cut off before any content": (
        "openai",
        chat_completion(None, "length", refusal=REFUSAL),
    ),
    "openai refusal cut off at an empty string": (
        "openai",
        chat_completion("", "length", refusal=REFUSAL),
    ),
    "groq no content": ("groq", chat_completion(None)),
    "groq cut off before any content": ("groq", chat_completion(None, "length")),
    "groq cut off at an empty string": ("groq", chat_completion("", "length")),
    "gemini blocked prompt": ("gemini", gemini_response(None, block_reason="SAFETY")),
    "gemini empty answer": ("gemini", gemini_response([], "STOP")),
    "gemini empty text part": ("gemini", gemini_response([{"text": ""}], "STOP")),
    "gemini cut off before any text": ("gemini", gemini_response([], "MAX_TOKENS")),
    "gemini thoughts only, cut off": ("gemini", gemini_response([THOUGHT], "MAX_TOKENS")),
    "gemini answer blocked": ("gemini", gemini_response([], "SAFETY")),
    "anthropic no blocks": ("anthropic", anthropic_message([])),
    "anthropic empty text block": ("anthropic", anthropic_message([{"type": "text", "text": ""}])),
    "anthropic thinking only, cut off": ("anthropic", anthropic_message([THINKING], "max_tokens")),
    "anthropic thinking only": ("anthropic", anthropic_message([THINKING])),
    "anthropic refusal": ("anthropic", anthropic_message([], "refusal")),
    "ollama cut off before any content": ("ollama_local", ollama_response("", "length")),
}

CUT_OFF: dict[str, tuple[str, dict[str, Any], str]] = {
    "openai": ("openai", chat_completion(CUT_OFF_JSON, "length"), "length"),
    "groq": ("groq", chat_completion(CUT_OFF_JSON, "length"), "length"),
    "gemini": ("gemini", gemini_response([{"text": CUT_OFF_JSON}], "MAX_TOKENS"), "MAX_TOKENS"),
    "anthropic": (
        "anthropic",
        anthropic_message([{"type": "text", "text": CUT_OFF_JSON}], "max_tokens"),
        "max_tokens",
    ),
    "ollama_local": ("ollama_local", ollama_response(CUT_OFF_JSON, "length"), "length"),
}


@pytest.mark.parametrize("json_mode", [True, False], ids=["json", "text"])
@pytest.mark.parametrize("case", sorted(NO_CONTENT))
def test_an_answer_with_no_content_ends_alike(case, json_mode):
    vendor, body = NO_CONTENT[case]

    assert batch_end(vendor, body, json_mode=json_mode) == online_end(
        vendor, body, json_mode=json_mode
    )


@pytest.mark.parametrize("json_mode", [True, False], ids=["json", "text"])
@pytest.mark.parametrize("vendor", sorted(CUT_OFF))
def test_an_answer_cut_off_midway_ends_alike(vendor, json_mode):
    _, body, _ = CUT_OFF[vendor]

    assert batch_end(vendor, body, json_mode=json_mode) == online_end(
        vendor, body, json_mode=json_mode
    )


class TestARefusal:
    def test_in_json_mode_it_is_a_parse_error_record_quoting_the_model(self):
        body = chat_completion(None, refusal=REFUSAL)

        end = batch_end("openai", body, json_mode=True)

        assert end == End(stored=[{"raw_response": "", "_parse_error": REFUSED}])

    def test_in_text_mode_it_fails_the_record_and_is_not_resent(self):
        body = chat_completion(None, refusal=REFUSAL)

        assert batch_end("openai", body, json_mode=False) == End(error=REFUSED, resent=False)

    def test_its_tokens_are_kept(self):
        """Online counts a refused call's tokens; a failed line reported none."""
        line = batch_line("openai", chat_completion(None, refusal=REFUSAL))

        assert line.usage == {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}


class TestAGeminiAnswerWithNoText:
    @pytest.mark.parametrize("json_mode", [True, False], ids=["json", "text"])
    def test_a_blocked_prompt_names_the_block_reason(self, json_mode):
        body = gemini_response(None, block_reason="SAFETY")
        message = "Gemini blocked the prompt (blockReason=SAFETY)"

        end = online_end("gemini", body, json_mode=json_mode)

        if json_mode:
            assert end == End(stored=[{"raw_response": "", "_parse_error": message}])
        else:
            assert end == End(error=message, resent=False)

    def test_an_empty_text_answer_is_left_to_on_empty(self):
        assert batch_end("gemini", gemini_response([], "STOP"), json_mode=False) == End(empty=True)

    def test_text_cut_off_before_it_began_is_resent(self):
        end = batch_end("gemini", gemini_response([], "MAX_TOKENS"), json_mode=False)

        assert end.resent is True
        assert "(stop_reason=MAX_TOKENS)" in (end.error or "")

    def test_a_thought_is_not_the_answer(self):
        """The SDK's `response.text` leaves thought parts out; batch read the first part."""
        body = gemini_response([THOUGHT, {"text": "The tide turns twice a day."}])

        end = batch_end("gemini", body, json_mode=False)

        assert end == End(stored=[{"raw_response": "The tide turns twice a day."}])
        assert end == online_end("gemini", body, json_mode=False)


class TestAnAnthropicMessageWithNoBlocks:
    def test_in_text_mode_it_is_left_to_on_empty(self):
        assert online_end("anthropic", anthropic_message([]), json_mode=False) == End(empty=True)

    def test_in_json_mode_it_is_a_parse_error_naming_the_stop_reason(self):
        end = batch_end("anthropic", anthropic_message([]), json_mode=True)

        assert "stop_reason=end_turn" in _parse_error(end)

    def test_one_the_model_did_not_end_itself_is_an_error(self):
        end = online_end("anthropic", anthropic_message([], "refusal"), json_mode=False)

        assert end == End(
            error="Empty response content from Anthropic API (stop_reason=refusal)", resent=False
        )

    def test_thinking_alone_is_not_resent_unless_it_was_cut_off(self):
        finished = batch_end("anthropic", anthropic_message([THINKING]), json_mode=False)
        cut_off = batch_end(
            "anthropic", anthropic_message([THINKING], "max_tokens"), json_mode=False
        )

        assert (finished.resent, cut_off.resent) == (False, True)


class TestAJsonAnswerCutOffMidway:
    @pytest.mark.parametrize("path", [online_end, batch_end], ids=["online", "batch"])
    @pytest.mark.parametrize("vendor", sorted(CUT_OFF))
    def test_it_is_a_parse_error_naming_the_stop_reason(self, vendor, path):
        _, body, reason = CUT_OFF[vendor]

        end = path(vendor, body, json_mode=True)

        assert f"stop_reason={reason}" in _parse_error(end)
        assert end.stored is not None
        assert end.stored[0]["raw_response"] == CUT_OFF_JSON

    @pytest.mark.parametrize("vendor", sorted(CUT_OFF))
    def test_in_text_mode_the_text_is_kept_as_written(self, vendor):
        _, body, _ = CUT_OFF[vendor]

        assert batch_end(vendor, body, json_mode=False) == End(
            stored=[{"raw_response": CUT_OFF_JSON}]
        )

    def test_cohere_which_has_no_batch_refuses_it_online_too(self):
        text = SimpleNamespace(type="text", text=CUT_OFF_JSON)
        reply = SimpleNamespace(
            finish_reason="MAX_TOKENS", message=SimpleNamespace(content=[text]), usage=None
        )
        with patch("cohere.ClientV2") as sdk:
            sdk.return_value.chat.return_value = reply
            (record,) = CohereClient.call_json("k", {"model_name": "m"}, "p", {"t": "x"}, None)

        assert record["raw_response"] == CUT_OFF_JSON
        assert "stop_reason=MAX_TOKENS" in record["_parse_error"]
