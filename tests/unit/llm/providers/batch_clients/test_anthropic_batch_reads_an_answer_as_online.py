"""An Anthropic batch result is read as the online client reads the same message.

A message with no text or tool block, as when thinking spent max_tokens, fails its record
with the stop reason; the thinking block is never the record's content.
"""

from __future__ import annotations

from typing import Any

from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.batch.services.shared import settle_unanswered
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient

THINKING = {"type": "thinking", "thinking": "Let me work out the quiz", "signature": "sig"}


def _client() -> AnthropicBatchClient:
    client = AnthropicBatchClient.__new__(AnthropicBatchClient)
    client.enable_prompt_caching = False
    return client


def _result(content: list[dict[str, Any]], stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "custom_id": "r1",
        "result": {
            "type": "succeeded",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": content,
                "stop_reason": stop_reason,
                "usage": {"input_tokens": 10, "output_tokens": 4096},
            },
        },
    }


class TestAnAnswerWithNoTextOrTool:
    """The line was answered, so it is no failed request; it has no content and says why."""

    def test_a_thinking_block_alone_fails_the_record_with_the_stop_reason(self):
        result = _client().parse_provider_response(_result([THINKING], "max_tokens"))

        assert BatchResultReconciler.is_answered(result) is False
        assert result.content is None
        assert "stop_reason=max_tokens" in (result.error or "")

    def test_a_redacted_thinking_block_alone_fails_it_too(self):
        redacted = {"type": "redacted_thinking", "data": "opaque"}

        result = _client().parse_provider_response(_result([redacted], "end_turn"))

        assert BatchResultReconciler.is_answered(result) is False
        assert "stop_reason=end_turn" in (result.error or "")

    def test_text_after_thinking_is_the_answer(self):
        text = {"type": "text", "text": '{"a": 1}'}

        result = _client().parse_provider_response(_result([THINKING, text]))

        assert (result.success, result.content) == (True, {"a": 1})

    def test_a_tool_answer_after_thinking_is_the_answer(self):
        tool = {"type": "tool_use", "id": "t1", "name": "quiz", "input": {"a": 1}}

        result = _client().parse_provider_response(_result([THINKING, tool], "tool_use"))

        assert (result.success, result.content) == (True, {"a": 1})

    def test_an_empty_content_list_is_left_to_on_empty(self):
        """In text mode; a JSON-mode read of it is the parse error online returns."""
        result = _client().parse_provider_response(_result([]))
        assert result.error is None
        assert "stop_reason=end_turn" in (result.parse_error or "")

        settle_unanswered([result], json_mode=False)

        assert (result.success, result.content) == (True, [])


class TestACutOffTextAnswer:
    """Online refuses to read text the output limit cut off; batch keeps it unparsed.

    In JSON mode the batch strategy then wraps the text as a parse error for repair.
    """

    def test_cut_off_json_is_not_completed_by_repair(self):
        text = '```json\n{"concepts": [{"concept": "ti'

        result = _client().parse_provider_response(
            _result([{"type": "text", "text": text}], "max_tokens")
        )

        assert (result.success, result.content) == (True, text)

    def test_a_finished_text_answer_is_still_read(self):
        text = '```json\n{"concepts": [{"concept": "tides"}]}\n```'

        result = _client().parse_provider_response(_result([{"type": "text", "text": text}]))

        assert result.content == {"concepts": [{"concept": "tides"}]}

    def test_a_tool_answer_is_returned_as_online_returns_it(self):
        tool = {"type": "tool_use", "id": "t1", "name": "quiz", "input": {"a": 1}}

        result = _client().parse_provider_response(_result([tool], "max_tokens"))

        assert result.content == {"a": 1}
