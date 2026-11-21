"""A provider's answer that the account's quota or credit is at its limit is not a rate limit.

Sent as HTTP 429 it was retried with back-off as a rate limit, and with any other
status it failed its record, so a run went on to fail or exhaust every record it had
left. HTTP 402 from any provider, and an answer with the status and the words the
provider sends for it (OpenAI and Ollama Cloud: a 429 or 403; Anthropic: a 400
`invalid_request_error` that says the credit balance is too low), wrap as
`QuotaExceededError`, which nothing retries. A 429 without those words is the rate
limit it was.

Each provider's own SDK answers the request, and the provider's error mapping wraps
what it raises.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from agent_actions.errors import QuotaExceededError, RateLimitError, VendorAPIError
from agent_actions.llm.providers.error_wrapper import (
    QUOTA_ANSWERS,
    error_for_status,
    find_quota_error,
    wrap_vendor_error,
)
from agent_actions.llm.providers.ollama.client import _ERROR_MAPPING_CLOUD, _OLLAMA_ERRORS
from agent_actions.processing.recovery.retry import RetryService, is_retriable_error
from tests.unit.llm.providers.test_which_http_statuses_each_provider_retries import (
    PROVIDERS,
    _ollama,
)

ALL = {**PROVIDERS, "ollama_cloud": (_ollama, _ERROR_MAPPING_CLOUD)}

OPENAI_QUOTA = {
    "error": {
        "message": "You exceeded your current quota, please check your plan and billing details.",
        "type": "insufficient_quota",
        "param": None,
        "code": "insufficient_quota",
    }
}
# What Anthropic sends when the credit balance is too low: HTTP 400, not 402 or 429.
ANTHROPIC_NO_CREDIT = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "Your credit balance is too low to access the Anthropic API. "
        "Please go to Plans & Billing to upgrade or purchase credits.",
    },
}
ANTHROPIC_BAD_REQUEST = {
    "type": "error",
    "error": {"type": "invalid_request_error", "message": "max_tokens: Field required"},
}
OLLAMA_USAGE_LIMIT = {"error": "you have reached your monthly usage limit"}
OLLAMA_USAGE_CREDITS = {"error": "add usage credits to continue"}

# provider -> each body that says the quota is used up, in the provider's own words
QUOTA_BODIES: dict[str, list[dict[str, Any]]] = {
    "openai": [OPENAI_QUOTA],
    "ollama_cloud": [OLLAMA_USAGE_LIMIT, OLLAMA_USAGE_CREDITS],
}


def _wrapped(provider: str, status: int, body: Any = None) -> Exception:
    call, mapping = ALL[provider]
    catch = _OLLAMA_ERRORS if provider.startswith("ollama") else Exception
    with pytest.raises(catch) as raised:
        call(status, body)
    return wrap_vendor_error(raised.value, "m", mapping, "r")


@pytest.mark.parametrize("provider", sorted(ALL))
def test_http_402_is_a_quota_stop_from_every_provider(provider):
    wrapped = _wrapped(provider, 402)

    assert isinstance(wrapped, QuotaExceededError)
    assert not is_retriable_error(wrapped)
    assert wrapped.context["vendor"] == ALL[provider][1].vendor_name


@pytest.mark.parametrize("status", [429, 403])
@pytest.mark.parametrize(
    ("provider", "body"),
    [(provider, body) for provider, bodies in sorted(QUOTA_BODIES.items()) for body in bodies],
)
def test_a_429_or_403_in_the_providers_words_for_a_used_up_quota_is_a_quota_stop(
    provider, body, status
):
    wrapped = _wrapped(provider, status, body)

    assert isinstance(wrapped, QuotaExceededError)
    assert not is_retriable_error(wrapped)


def test_an_anthropic_400_that_says_the_credit_balance_is_too_low_is_a_quota_stop():
    wrapped = _wrapped("anthropic", 400, ANTHROPIC_NO_CREDIT)

    assert isinstance(wrapped, QuotaExceededError)
    assert not is_retriable_error(wrapped)
    assert "credit balance is too low" in wrapped.provider_message


def test_any_other_anthropic_400_is_still_an_api_error():
    assert type(_wrapped("anthropic", 400, ANTHROPIC_BAD_REQUEST)) is VendorAPIError


def test_the_anthropic_credit_words_from_another_provider_are_not_a_quota_stop():
    assert type(_wrapped("openai", 400, ANTHROPIC_NO_CREDIT)) is VendorAPIError


@pytest.mark.parametrize("provider", sorted(ALL))
def test_a_plain_429_is_still_a_rate_limit_and_is_retried(provider):
    wrapped = _wrapped(provider, 429)

    assert type(wrapped) is RateLimitError
    assert is_retriable_error(wrapped)


@pytest.mark.parametrize("provider", sorted(ALL))
def test_a_plain_403_is_still_an_api_error(provider):
    wrapped = _wrapped(provider, 403)

    assert type(wrapped) is VendorAPIError


@pytest.mark.parametrize("provider", ["gemini", "groq", "cohere", "ollama"])
def test_a_provider_with_no_known_words_reads_a_429_as_a_rate_limit_whatever_it_says(provider):
    """Only the 402 rule applies where no body of the provider's is known."""
    assert provider not in QUOTA_ANSWERS

    wrapped = _wrapped(provider, 429, OPENAI_QUOTA)

    assert type(wrapped) is RateLimitError


def test_another_providers_words_are_not_read_as_this_ones():
    assert type(_wrapped("openai", 429, OLLAMA_USAGE_LIMIT)) is RateLimitError


def test_the_error_keeps_the_providers_own_text():
    wrapped = _wrapped("ollama_cloud", 429, OLLAMA_USAGE_LIMIT)

    assert isinstance(wrapped, QuotaExceededError)
    assert "you have reached your monthly usage limit" in wrapped.provider_message
    assert "ollama_cloud" in str(wrapped)


def test_a_status_with_no_exception_reads_402_as_a_quota_stop():
    assert isinstance(error_for_status(402, "credit balance is too low"), QuotaExceededError)
    assert type(error_for_status(429, "slow down")) is RateLimitError


class TestTheRetryPolicy:
    def _attempts(self, error: Exception) -> int:
        calls = []

        def operation():
            calls.append(1)
            raise error

        service = RetryService(max_attempts=3, base_delay=0.001, max_delay=0.001)
        try:
            service.execute(operation)
        except type(error):
            pass
        return len(calls)

    def test_a_quota_stop_is_raised_at_its_first_attempt(self):
        assert self._attempts(_wrapped("ollama_cloud", 429, OLLAMA_USAGE_LIMIT)) == 1

    def test_a_plain_rate_limit_is_retried_to_max_attempts(self):
        assert self._attempts(_wrapped("ollama_cloud", 429)) == 3


class TestAQuotaAnswerWrappedByABatchClient:
    """A batch client raises its own error with the SDK's as the cause."""

    def test_it_is_found_in_the_cause_chain(self):
        call, _ = ALL["anthropic"]
        with pytest.raises(Exception) as raised:  # noqa: PT011 - the SDK's own status error
            call(400, ANTHROPIC_NO_CREDIT)
        outer = VendorAPIError("Anthropic API error during batch submission", cause=raised.value)
        outer.__cause__ = raised.value

        found = find_quota_error(outer, "anthropic")

        assert isinstance(found, QuotaExceededError)
        assert "credit balance is too low" in found.provider_message

    def test_an_error_that_is_not_a_quota_answer_finds_nothing(self):
        call, _ = ALL["anthropic"]
        with pytest.raises(Exception) as raised:  # noqa: PT011 - the SDK's own status error
            call(429)

        assert find_quota_error(raised.value, "anthropic") is None


@pytest.mark.parametrize("status", [429, 403])
def test_an_sdk_message_that_leaves_out_the_error_code_is_still_read_by_its_type(status):
    """Newer OpenAI SDKs put only the body's message in the error text, not its code."""
    import httpx
    import openai

    from agent_actions.llm.providers.openai.client import _ERROR_MAPPING

    error_class = openai.RateLimitError if status == 429 else openai.PermissionDeniedError
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com"))
    message = f"Error code: {status} - {OPENAI_QUOTA['error']['message']}"
    error = error_class(message, response=response, body=OPENAI_QUOTA["error"])
    assert "insufficient_quota" not in str(error)

    wrapped = wrap_vendor_error(error, "m", _ERROR_MAPPING, "r")

    assert isinstance(wrapped, QuotaExceededError)
    assert find_quota_error(error, "openai") is not None


@pytest.mark.parametrize("status", [429, 403])
def test_an_sdk_error_whose_code_alone_holds_the_words_is_read_by_its_code(status):
    """The message and the type say nothing of the quota; only the code (and the body) do."""
    import httpx
    import openai

    from agent_actions.llm.providers.openai.client import _ERROR_MAPPING

    body = {"message": "Request refused.", "type": "requests", "code": "insufficient_quota"}
    error_class = openai.RateLimitError if status == 429 else openai.PermissionDeniedError
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com"))
    error = error_class(f"Error code: {status} - Request refused.", response=response, body=body)
    assert "insufficient_quota" not in str(error) and error.type == "requests"

    assert isinstance(wrap_vendor_error(error, "m", _ERROR_MAPPING, "r"), QuotaExceededError)


class TestTheOpenAiSdkSendsNoQuotaAnswerAgain:
    """The SDK sends a 429 again, twice by default, before agac sees it; not a quota 429."""

    def _requests(self, body: Any) -> int:
        import httpx
        import openai

        from agent_actions.llm.providers.openai.client import without_quota_retries

        sent = []

        def answer(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(429, json=body)

        client = without_quota_retries(
            openai.OpenAI(
                api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(answer))
            ),
            "openai",
        )
        with (
            patch.object(openai._base_client.time, "sleep"),
            pytest.raises(openai.RateLimitError),
        ):
            client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])
        return len(sent)

    def test_a_quota_429_is_sent_once(self):
        assert self._requests(OPENAI_QUOTA) == 1

    def test_a_plain_429_is_still_sent_again_by_the_sdk(self):
        assert self._requests({"error": {"message": "slow down", "type": "requests"}}) == 3
