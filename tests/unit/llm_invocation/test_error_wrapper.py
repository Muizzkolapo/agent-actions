"""Tests for the unified vendor error wrapper.

Validates that wrap_vendor_error() correctly classifies vendor SDK exceptions
into unified error types (RateLimitError, NetworkError, VendorAPIError).
"""

from unittest.mock import MagicMock, patch

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

    def test_returns_none_without_response(self):
        e = Exception("no response")
        assert _extract_retry_after(e) is None

    def test_returns_none_with_none_response(self):
        e = Exception("null response")
        e.response = None
        assert _extract_retry_after(e) is None

    def test_extracts_float_retry_after(self):
        e = Exception("rate limited")
        e.response = MagicMock()
        e.response.headers = {"retry-after": "30.5"}
        assert _extract_retry_after(e) == 30.5

    def test_returns_none_for_invalid_value(self):
        e = Exception("bad header")
        e.response = MagicMock()
        e.response.headers = {"retry-after": "not-a-number"}
        assert _extract_retry_after(e) is None


class TestWrapVendorErrorTypeBased:
    """Tests for type-based error classification (OpenAI/Anthropic/Groq style)."""

    @patch("agent_actions.llm.providers.error_wrapper.fire_event")
    def test_rate_limit_error(self, mock_fire):
        e = FakeRateLimitError("too many requests")
        result = wrap_vendor_error(e, "gpt-4", TYPE_BASED_MAPPING, "req-1")

        assert isinstance(result, RateLimitError)
        assert "rate limit" in str(result)
        mock_fire.assert_called_once()

    @patch("agent_actions.llm.providers.error_wrapper.fire_event")
    def test_network_error_connection(self, mock_fire):
        e = FakeConnectionError("connection refused")
        result = wrap_vendor_error(e, "gpt-4", TYPE_BASED_MAPPING)

        assert isinstance(result, NetworkError)
        mock_fire.assert_called_once()

    @patch("agent_actions.llm.providers.error_wrapper.fire_event")
    def test_network_error_timeout(self, mock_fire):
        e = FakeTimeoutError("timed out")
        result = wrap_vendor_error(e, "gpt-4", TYPE_BASED_MAPPING)

        assert isinstance(result, NetworkError)

    @patch("agent_actions.llm.providers.error_wrapper.fire_event")
    def test_base_api_error(self, mock_fire):
        e = FakeAPIError("bad request")
        result = wrap_vendor_error(e, "gpt-4", TYPE_BASED_MAPPING)

        assert isinstance(result, VendorAPIError)

    def test_unknown_error_returned_as_is(self):
        e = ValueError("something else")
        result = wrap_vendor_error(e, "gpt-4", TYPE_BASED_MAPPING)

        assert result is e


class TestWrapVendorErrorStatusCodeBased:
    """Tests for status-code-based error classification (Cohere/Mistral style)."""

    @patch("agent_actions.llm.providers.error_wrapper.fire_event")
    def test_status_429_is_rate_limit(self, mock_fire):
        e = FakeStatusCodeError(429)
        result = wrap_vendor_error(e, "command-r", STATUS_CODE_MAPPING)

        assert isinstance(result, RateLimitError)

    @patch("agent_actions.llm.providers.error_wrapper.fire_event")
    def test_status_503_is_network_error(self, mock_fire):
        e = FakeStatusCodeError(503)
        result = wrap_vendor_error(e, "command-r", STATUS_CODE_MAPPING)

        assert isinstance(result, NetworkError)

    @patch("agent_actions.llm.providers.error_wrapper.fire_event")
    def test_status_502_is_network_error(self, mock_fire):
        e = FakeStatusCodeError(502)
        result = wrap_vendor_error(e, "command-r", STATUS_CODE_MAPPING)

        assert isinstance(result, NetworkError)

    @patch("agent_actions.llm.providers.error_wrapper.fire_event")
    def test_other_status_is_vendor_api_error(self, mock_fire):
        e = FakeStatusCodeError(400)
        result = wrap_vendor_error(e, "command-r", STATUS_CODE_MAPPING)

        assert isinstance(result, VendorAPIError)

    @patch("agent_actions.llm.providers.error_wrapper.fire_event")
    def test_extra_network_types(self, mock_fire):
        e = ConnectionError("refused")
        result = wrap_vendor_error(e, "command-r", STATUS_CODE_MAPPING)

        assert isinstance(result, NetworkError)
