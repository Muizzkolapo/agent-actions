"""An Anthropic usage, of an online response or a batch line, names its cache read and cache write tokens."""

from __future__ import annotations

from anthropic.types import Message

from agent_actions.output.response.response_builder import ResponseBuilder, UsageResult

USAGE = {
    "input_tokens": 40,
    "output_tokens": 7,
    "cache_read_input_tokens": 1200,
    "cache_creation_input_tokens": 300,
}


def _message(usage: dict[str, int]) -> Message:
    return Message.model_validate(
        {
            "id": "m",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-6",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": usage,
        }
    )


def test_an_online_response_names_both():
    usage = ResponseBuilder.extract_usage(_message(USAGE), "anthropic")

    assert (usage.cache_read_tokens, usage.cache_creation_tokens) == (1200, 300)


def test_a_batch_line_names_both():
    line_usage = _message(USAGE).usage.model_dump()

    usage = ResponseBuilder.batch_usage(line_usage)

    assert (usage.cache_read_tokens, usage.cache_creation_tokens) == (1200, 300)


def test_online_and_batch_read_one_usage_alike():
    message = _message(USAGE)

    assert ResponseBuilder.extract_usage(message, "anthropic") == ResponseBuilder.batch_usage(
        message.usage.model_dump()
    )


def test_the_prompt_tokens_still_count_the_whole_prompt():
    usage = ResponseBuilder.extract_usage(_message(USAGE), "anthropic")

    assert usage.prompt_tokens == 40 + 1200 + 300
    assert usage.total_tokens == usage.prompt_tokens + 7


def test_a_response_that_used_no_cache_names_none():
    usage = ResponseBuilder.extract_usage(
        _message({"input_tokens": 40, "output_tokens": 7}), "anthropic"
    )

    assert (usage.cache_read_tokens, usage.cache_creation_tokens) == (0, 0)


def test_another_vendors_usage_names_none():
    usage = ResponseBuilder.batch_usage({"prompt_tokens": 5, "completion_tokens": 2})

    assert usage == UsageResult(prompt_tokens=5, completion_tokens=2, total_tokens=7)
