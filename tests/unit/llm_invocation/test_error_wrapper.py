"""Tests for the unified vendor error wrapper.

Validates that wrap_vendor_error() correctly classifies vendor SDK exceptions
into unified error types (RateLimitError, NetworkError, VendorAPIError).
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import NetworkError, RateLimitError, VendorAPIError
from agent_actions.llm.providers.error_wrapper import (
    VendorErrorMapping,
    _extract_retry_after,
    wrap_vendor_error,
)


class FakeRateLimitError(Exception):
    pass


class FakeConnectionError(Exception):
    pass


class FakeTimeoutError(Exception):
    pass


class FakeServerError(Exception):
    pass


class FakeAPIError(Exception):
    pass


class FakeStatusCodeError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class FakeCodeOnlyError(Exception):
    """Mimics google-genai errors that use .code instead of .status_code."""

    def __init__(self, code):
        self.code = code
        super().__init__(f"HTTP {code}")


TYPE_BASED_MAPPING = VendorErrorMapping(
    vendor_name="test_vendor",
    rate_limit_types=(FakeRateLimitError,),
    network_error_types=(FakeConnectionError, FakeTimeoutError, FakeServerError),
    base_api_error_type=FakeAPIError,
    supports_retry_after=True,
)

STATUS_CODE_MAPPING = VendorErrorMapping(
    vendor_name="status_vendor",
    status_code_error_types=(FakeStatusCodeError,),
    extra_network_types=(ConnectionError, TimeoutError),
)


class TestExtractRetryAfter:
    """Tests for _extract_retry_after helper."""

    @pytest.mark.parametrize(
        "setup,expected",
        [
            pytest.param(lambda e: None, None, id="no_response_attr"),
            pytest.param(lambda e: setattr(e, "response", None), None, id="none_response"),
            pytest.param(
                lambda e: setattr(e, "response", MagicMock(headers={"retry-after": "30.5"})),
                30.5,
                id="valid_float",
            ),
            pytest.param(
                lambda e: setattr(
                    e, "response", MagicMock(headers={"retry-after": "not-a-number"})
                ),
                None,
                id="invalid_value",
            ),
        ],
    )
    def test_extract_retry_after(self, setup, expected):
        e = Exception("test")
        setup(e)
        assert _extract_retry_after(e) == expected


class TestWrapVendorErrorTypeBased:
    """Tests for type-based error classification (OpenAI/Anthropic/Groq style)."""

    @pytest.mark.parametrize(
        "exception,expected_type",
        [
            pytest.param(FakeRateLimitError("too many requests"), RateLimitError, id="rate_limit"),
            pytest.param(FakeConnectionError("connection refused"), NetworkError, id="connection"),
            pytest.param(FakeTimeoutError("timed out"), NetworkError, id="timeout"),
            pytest.param(FakeAPIError("bad request"), VendorAPIError, id="api_error"),
        ],
    )
    @patch("agent_actions.llm.providers.error_wrapper.fire_event")
    def test_classified_errors(self, mock_fire, exception, expected_type):
        result = wrap_vendor_error(exception, "gpt-4", TYPE_BASED_MAPPING, "req-1")
        assert isinstance(result, expected_type)
        mock_fire.assert_called_once()

    def test_unknown_error_returned_as_is(self):
        e = ValueError("something else")
        result = wrap_vendor_error(e, "gpt-4", TYPE_BASED_MAPPING)
        assert result is e


class TestWrapVendorErrorStatusCodeBased:
    """Tests for status-code-based error classification (Cohere/Mistral style)."""

    @pytest.mark.parametrize(
        "status_code,expected_type",
        [
            pytest.param(429, RateLimitError, id="429_rate_limit"),
            pytest.param(503, NetworkError, id="503_network"),
            pytest.param(502, NetworkError, id="502_network"),
            pytest.param(400, VendorAPIError, id="400_api_error"),
        ],
    )
    @patch("agent_actions.llm.providers.error_wrapper.fire_event")
    def test_status_code_classification(self, mock_fire, status_code, expected_type):
        e = FakeStatusCodeError(status_code)
        result = wrap_vendor_error(e, "command-r", STATUS_CODE_MAPPING)
        assert isinstance(result, expected_type)

    @patch("agent_actions.llm.providers.error_wrapper.fire_event")
    def test_extra_network_types(self, mock_fire):
        e = ConnectionError("refused")
        result = wrap_vendor_error(e, "command-r", STATUS_CODE_MAPPING)
        assert isinstance(result, NetworkError)


class TestWrapVendorErrorCodeAttribute:
    """Tests for .code attribute fallback (google-genai style)."""

    CODE_ONLY_MAPPING = VendorErrorMapping(
        vendor_name="gemini",
        status_code_error_types=(FakeCodeOnlyError,),
    )

    @pytest.mark.parametrize(
        "code,expected_type",
        [
            pytest.param(429, RateLimitError, id="429_rate_limit"),
            pytest.param(500, NetworkError, id="500_network"),
            pytest.param(503, NetworkError, id="503_network"),
            pytest.param(400, VendorAPIError, id="400_api_error"),
        ],
    )
    @patch("agent_actions.llm.providers.error_wrapper.fire_event")
    def test_code_attribute_classification(self, mock_fire, code, expected_type):
        e = FakeCodeOnlyError(code)
        result = wrap_vendor_error(e, "gemini-pro", self.CODE_ONLY_MAPPING)
        assert isinstance(result, expected_type)
