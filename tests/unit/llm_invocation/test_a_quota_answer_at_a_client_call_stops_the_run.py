"""A client that raises `QuotaExceededError` ends the run where every model call is made.

Raised as an ordinary error it would fail its record, as any error of one record does:
the handlers above the call cannot tell it from one. `invoke_client` raises
`ProviderQuotaStop` in its place, which is not an `Exception`, so none of them sees it.
"""

from unittest.mock import patch

import pytest

from agent_actions.errors import ProviderQuotaStop, QuotaExceededError, VendorAPIError
from agent_actions.llm.realtime.services.invocation import ClientInvocationService


class _Client:
    def __init__(self, error: Exception):
        self.error = error

    def invoke(self, *args, **kwargs):
        raise self.error


def _invoke(error: Exception):
    with patch(
        "agent_actions.llm.realtime.services.invocation._resolve_client",
        return_value=_Client(error),
    ):
        return ClientInvocationService.invoke_client(
            "ollama_cloud", {"model_name": "m"}, "prompt", "context", None, "record"
        )


def test_a_quota_answer_is_raised_as_a_stop_that_names_the_provider_and_its_text():
    quota = QuotaExceededError(
        "ollama_cloud quota or billing stop: monthly usage limit reached",
        context={"vendor": "ollama_cloud", "provider_message": "monthly usage limit reached"},
    )

    with pytest.raises(ProviderQuotaStop) as stopped:
        _invoke(quota)

    assert stopped.value.provider == "ollama_cloud"
    assert stopped.value.provider_message == "monthly usage limit reached"
    assert stopped.value.__cause__ is quota
    assert str(stopped.value) == (
        "Provider quota or billing stop (ollama_cloud): monthly usage limit reached. "
        "Add credits, then run again to resume."
    )


def test_the_stop_is_not_an_exception_a_record_handler_catches():
    assert not issubclass(ProviderQuotaStop, Exception)


def test_any_other_provider_error_is_raised_as_it_was():
    error = VendorAPIError("ollama_cloud API error: no such model")

    with pytest.raises(VendorAPIError) as raised:
        _invoke(error)

    assert raised.value is error
