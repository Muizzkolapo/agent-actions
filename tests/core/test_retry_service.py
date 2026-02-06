"""Tests for RetryService.

Tests based on RFC_recovery.md test cases for retry mechanism.
"""

import pytest
from unittest.mock import Mock, call

from agent_actions.processing.recovery.retry import (
    RetryService,
    RetryResult,
    classify_error,
    is_retriable_error,
    create_retry_service_from_config,
    RETRIABLE_ERRORS,
)
from agent_actions.errors import NetworkError, RateLimitError, VendorAPIError


class TestRetryResult:
    """Tests for RetryResult dataclass."""

    def test_needed_retry_false_for_first_attempt(self):
        """No retry needed when success on first attempt."""
        result = RetryResult(response="success", attempts=1)
        assert not result.needed_retry

    def test_needed_retry_true_for_multiple_attempts(self):
        """Retry was needed if attempts > 1."""
        result = RetryResult(response="success", attempts=2, reason="timeout")
        assert result.needed_retry


class TestClassifyError:
    """Tests for error classification."""

    def test_classify_rate_limit_error(self):
        """RateLimitError classified as rate_limit."""
        error = RateLimitError("Rate limit exceeded")
        assert classify_error(error) == "rate_limit"

    def test_classify_timeout_error(self):
        """NetworkError with timeout classified as timeout."""
        error = NetworkError("Request timeout")
        assert classify_error(error) == "timeout"

    def test_classify_network_error(self):
        """NetworkError without timeout classified as network_error."""
        error = NetworkError("Connection refused")
        assert classify_error(error) == "network_error"

    def test_classify_vendor_api_error(self):
        """VendorAPIError classified as api_error."""
        error = VendorAPIError("API error")
        assert classify_error(error) == "api_error"

    def test_classify_unknown_error(self):
        """Unknown error type classified as unknown."""
        error = ValueError("Some error")
        assert classify_error(error) == "unknown"


class TestIsRetriableError:
    """Tests for is_retriable_error function."""

    def test_network_error_is_retriable(self):
        """NetworkError is retriable."""
        assert is_retriable_error(NetworkError("timeout"))

    def test_rate_limit_error_is_retriable(self):
        """RateLimitError is retriable."""
        assert is_retriable_error(RateLimitError("rate limited"))

    def test_vendor_api_error_not_retriable(self):
        """VendorAPIError is not retriable by default."""
        assert not is_retriable_error(VendorAPIError("api error"))

    def test_value_error_not_retriable(self):
        """ValueError is not retriable."""
        assert not is_retriable_error(ValueError("bad value"))


class TestRetryServiceOnlineSuccess:
    """Tests for retry success scenarios (online mode)."""

    def test_retry_online_success_on_first_attempt(self):
        """No retry needed when LLM call succeeds on first attempt."""
        service = RetryService(max_attempts=3)
        operation = Mock(return_value="success response")

        result = service.execute(operation)

        assert result.response == "success response"
        assert result.attempts == 1
        assert not result.needed_retry
        assert not result.exhausted
        operation.assert_called_once()

    def test_retry_online_success_after_timeout(self):
        """Retry succeeds after first attempt times out."""
        service = RetryService(max_attempts=3)
        operation = Mock(side_effect=[NetworkError("timeout"), "success response"])

        result = service.execute(operation)

        assert result.response == "success response"
        assert result.attempts == 2
        assert result.needed_retry
        assert result.reason == "timeout"
        assert not result.exhausted
        assert operation.call_count == 2

    def test_retry_online_success_after_rate_limit(self):
        """Retry succeeds after rate limit error."""
        service = RetryService(max_attempts=3)
        operation = Mock(side_effect=[RateLimitError("rate limited"), "success response"])

        result = service.execute(operation)

        assert result.response == "success response"
        assert result.attempts == 2
        assert result.reason == "rate_limit"
        assert not result.exhausted

    def test_retry_online_success_after_multiple_failures(self):
        """Retry succeeds after multiple failures."""
        service = RetryService(max_attempts=5)
        operation = Mock(
            side_effect=[
                NetworkError("timeout"),
                RateLimitError("rate limited"),
                NetworkError("connection error"),
                "success response",
            ]
        )

        result = service.execute(operation)

        assert result.response == "success response"
        assert result.attempts == 4
        assert result.needed_retry
        assert not result.exhausted


class TestRetryServiceOnlineExhausted:
    """Tests for retry exhaustion scenarios (online mode)."""

    def test_retry_online_exhausted_raises(self):
        """on_exhausted=raise returns exhausted result (caller decides whether to raise)."""
        service = RetryService(max_attempts=3, on_exhausted="raise")
        error = NetworkError("persistent timeout")
        operation = Mock(side_effect=error)

        # Changed behavior: retry_service always returns result, never raises
        # The decision to raise is made by ProcessingPipeline/BatchResultProcessor
        result = service.execute(operation)

        assert result.response is None
        assert result.attempts == 3
        assert result.exhausted
        assert result.reason == "timeout"
        assert "persistent timeout" in result.last_error
        assert operation.call_count == 3
        assert service.on_exhausted == "raise"  # Config is preserved for caller to check

    def test_retry_online_exhausted_returns_last(self):
        """on_exhausted=return_last returns None after max_attempts."""
        service = RetryService(max_attempts=3, on_exhausted="return_last")
        operation = Mock(side_effect=NetworkError("persistent timeout"))

        result = service.execute(operation)

        assert result.response is None
        assert result.attempts == 3
        assert result.exhausted
        assert result.reason == "timeout"
        assert "persistent timeout" in result.last_error


class TestRetryServiceMetadata:
    """Tests for retry metadata recording."""

    def test_retry_online_metadata_recorded(self):
        """_recovery.retry contains attempts and reason."""
        service = RetryService(max_attempts=3)
        operation = Mock(side_effect=[NetworkError("timeout"), "success response"])

        result = service.execute(operation)

        assert result.attempts == 2
        assert result.reason == "timeout"
        assert result.needed_retry

    def test_no_metadata_when_no_retry(self):
        """No retry reason recorded when success on first attempt."""
        service = RetryService(max_attempts=3)
        operation = Mock(return_value="success response")

        result = service.execute(operation)

        assert result.attempts == 1
        assert result.reason is None
        assert not result.needed_retry


class TestRetryServiceNonRetriableErrors:
    """Tests for non-retriable error handling."""

    def test_non_retriable_error_raises_immediately(self):
        """Non-retriable errors are raised immediately without retry."""
        service = RetryService(max_attempts=3)
        error = ValueError("Invalid input")
        operation = Mock(side_effect=error)

        with pytest.raises(ValueError) as exc_info:
            service.execute(operation)

        assert exc_info.value is error
        operation.assert_called_once()  # No retry

    def test_vendor_api_error_raises_immediately(self):
        """VendorAPIError raises immediately (not in RETRIABLE_ERRORS)."""
        service = RetryService(max_attempts=3)
        error = VendorAPIError("API error")
        operation = Mock(side_effect=error)

        with pytest.raises(VendorAPIError) as exc_info:
            service.execute(operation)

        assert exc_info.value is error
        operation.assert_called_once()


class TestCreateRetryServiceFromConfig:
    """Tests for create_retry_service_from_config factory."""

    def test_returns_none_when_config_is_none(self):
        """Returns None when no config provided."""
        assert create_retry_service_from_config(None) is None

    def test_returns_none_when_disabled(self):
        """Returns None when retry is disabled."""
        config = {"enabled": False, "max_attempts": 3}
        assert create_retry_service_from_config(config) is None

    def test_creates_service_with_defaults(self):
        """Creates service with default values."""
        config = {"enabled": True}
        service = create_retry_service_from_config(config)

        assert service is not None
        assert service.max_attempts == 3
        assert service.on_exhausted == "return_last"

    def test_creates_service_with_custom_config(self):
        """Creates service with custom configuration."""
        config = {
            "enabled": True,
            "max_attempts": 5,
            "on_exhausted": "raise",
        }
        service = create_retry_service_from_config(config)

        assert service is not None
        assert service.max_attempts == 5
        assert service.on_exhausted == "raise"

    def test_enabled_defaults_to_true(self):
        """Retry is enabled by default if key is missing."""
        config = {"max_attempts": 3}
        service = create_retry_service_from_config(config)

        assert service is not None


class TestRetryServiceEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_max_attempts_of_one_means_no_retry(self):
        """max_attempts=1 means no retry even on error."""
        service = RetryService(max_attempts=1, on_exhausted="return_last")
        operation = Mock(side_effect=NetworkError("timeout"))

        result = service.execute(operation)

        assert result.attempts == 1
        assert result.exhausted
        operation.assert_called_once()

    def test_max_attempts_clamped_to_at_least_one(self):
        """max_attempts is clamped to at least 1."""
        service = RetryService(max_attempts=0)
        assert service.max_attempts == 1

    def test_context_included_in_logging(self):
        """Context string is included in logging."""
        service = RetryService(max_attempts=2)
        operation = Mock(side_effect=NetworkError("timeout"))

        # Should not raise, context is for logging only
        result = service.execute(operation, context="test_action")

        assert result.exhausted
