"""Gemini's thinking tokens are output: its total counts them, and so must the output count."""

from google.genai import types

from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient
from agent_actions.output.response.response_builder import ResponseBuilder


def _online(**usage: int | None) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        usage_metadata=types.GenerateContentResponseUsageMetadata(**usage)
    )


def test_online_output_includes_thinking_tokens():
    response = _online(
        prompt_token_count=10,
        candidates_token_count=20,
        thoughts_token_count=70,
        total_token_count=100,
    )

    usage = ResponseBuilder.extract_usage(response, "gemini")

    assert usage.completion_tokens == 90
    assert usage.prompt_tokens + usage.completion_tokens == usage.total_tokens


def test_online_output_without_thinking_is_the_candidates_count():
    response = _online(prompt_token_count=10, candidates_token_count=20, total_token_count=30)

    assert ResponseBuilder.extract_usage(response, "gemini").completion_tokens == 20


def test_batch_output_includes_thinking_tokens():
    client = GeminiBatchClient.__new__(GeminiBatchClient)
    raw = {
        "key": "r1",
        "response": {
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 20,
                "thoughtsTokenCount": 70,
                "totalTokenCount": 100,
            }
        },
    }

    usage = client._extract_usage_from_response(raw)

    assert usage == {"prompt_tokens": 10, "completion_tokens": 90, "total_tokens": 100}


def test_batch_output_without_any_count_stays_unknown():
    client = GeminiBatchClient.__new__(GeminiBatchClient)

    usage = client._extract_usage_from_response({"key": "r1", "response": {}})

    assert usage is not None
    assert usage["completion_tokens"] is None
