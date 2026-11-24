"""Each scenario fault reaches the framework as a real vendor's client hands it over.

A rate limit, a timeout and a server error raise the errors ``wrap_vendor_error`` makes,
which the retry policy retries. A refusal, an empty answer, a cut-off answer and text
that is not JSON end as the chat clients end them: a ``_parse_error`` record in JSON mode,
the error ``chat_no_answer`` names in text mode. In a batch each is the result line such
a vendor writes, and the mock batch client reads it as the OpenAI batch client does.
"""

from __future__ import annotations

import json

import pytest

from agent_actions.errors import (
    NetworkError,
    RateLimitError,
    ResponseTruncatedError,
    VendorAPIError,
)
from agent_actions.llm.providers.agac import faults
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.llm.providers.error_wrapper import (
    cut_off_parse_error,
    empty_parse_error,
    refusal_text,
)
from agent_actions.processing.recovery.retry import is_retriable_error

HONEST = {"summary": "calm sea", "tone": "calm"}


@pytest.mark.parametrize(
    ("kind", "error"),
    [("rate_limit", RateLimitError), ("timeout", NetworkError), ("server_error", NetworkError)],
)
def test_a_transport_fault_raises_a_retried_error_in_both_modes(kind, error):
    with pytest.raises(error) as json_mode:
        faults.json_answer(kind, HONEST, "gpt-4o-mini")
    with pytest.raises(error) as text_mode:
        faults.text_answer(kind, "gpt-4o-mini")

    assert is_retriable_error(json_mode.value) and is_retriable_error(text_mode.value)


@pytest.mark.parametrize(
    ("kind", "parse_error"),
    [
        ("refusal", refusal_text(faults.REFUSAL)),
        ("empty", empty_parse_error("stop")),
        ("truncated", cut_off_parse_error("length")),
        ("invalid_json", "Failed to parse JSON from LLM response"),
    ],
)
def test_an_answer_fault_is_a_parse_error_record_in_json_mode(kind, parse_error):
    [record] = faults.json_answer(kind, HONEST, "gpt-4o-mini")

    assert record["_parse_error"] == parse_error
    if kind == "truncated":
        assert json.dumps(HONEST).startswith(record["raw_response"])
        assert record["raw_response"] != json.dumps(HONEST)


@pytest.mark.parametrize(
    ("kind", "error", "retried"),
    [
        ("refusal", VendorAPIError, False),
        ("empty", VendorAPIError, False),
        ("truncated", ResponseTruncatedError, True),
    ],
)
def test_an_answer_fault_raises_in_text_mode(kind, error, retried):
    with pytest.raises(error) as caught:
        faults.text_answer(kind, "gpt-4o-mini")

    assert is_retriable_error(caught.value) is retried


def test_text_that_is_not_json_is_returned_in_text_mode():
    assert faults.text_answer("invalid_json", "gpt-4o-mini") == faults.NOT_JSON


def _line(content: str = json.dumps(HONEST)) -> dict:
    return {
        "id": "batch_req_1",
        "custom_id": "rec-1",
        "response": {
            "status_code": 200,
            "body": {
                "model": "agac-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            },
        },
        "error": None,
    }


def _parsed(kind: str):
    return AgacBatchClient().parse_provider_response(faults.batch_line(kind, _line()))


@pytest.mark.parametrize(("kind", "status"), [("rate_limit", 429), ("server_error", 503)])
def test_a_transport_fault_is_a_failed_batch_line_with_its_status(kind, status):
    result = _parsed(kind)

    assert not result.success
    assert result.error_status == status


def test_a_timeout_is_a_failed_batch_line():
    result = _parsed("timeout")

    assert not result.success and "timed out" in result.error


@pytest.mark.parametrize(
    ("kind", "parse_error"),
    [
        ("refusal", refusal_text(faults.REFUSAL)),
        ("empty", empty_parse_error("stop")),
        ("truncated", cut_off_parse_error("length")),
    ],
)
def test_an_answer_fault_is_a_batch_line_with_no_usable_answer(kind, parse_error):
    result = _parsed(kind)

    assert result.success
    assert result.parse_error == parse_error


def test_text_that_is_not_json_is_a_batch_line_no_parse_reads():
    result = _parsed("invalid_json")

    assert result.success
    assert not isinstance(result.content, dict)


def test_an_honest_line_still_reads_as_its_answer():
    result = AgacBatchClient().parse_provider_response(_line())

    assert result.success and result.content == HONEST and result.parse_error is None
