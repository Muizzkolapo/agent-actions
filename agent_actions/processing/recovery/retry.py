"""Retry service for handling transport-layer failures in LLM calls."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_actions.errors import NetworkError, RateLimitError, VendorAPIError
from agent_actions.logging import fire_event
from agent_actions.logging.events.validation_events import RetryExhaustedEvent

logger = logging.getLogger(__name__)


RETRIABLE_ERRORS = (NetworkError, RateLimitError)


@dataclass
class RetryResult:
    """Result of a retry-wrapped operation."""

    response: Any | None
    attempts: int = 1
    reason: str | None = None
    exhausted: bool = False
    last_error: str | None = None

    @property
    def needed_retry(self) -> bool:
        """Return True if a transport-layer failure occurred."""
        return self.attempts > 1 or self.exhausted


def classify_error(error: Exception) -> str:
    """Classify an error into a retry reason string."""
    error_str = str(error).lower()

    if isinstance(error, RateLimitError):
        return "rate_limit"
    elif isinstance(error, NetworkError):
        if "timeout" in error_str:
            return "timeout"
        return "network_error"
    elif isinstance(error, VendorAPIError):
        return "api_error"
    else:
        return "unknown"


def is_retriable_error(error: Exception) -> bool:
    """Return True if the error is retriable (NetworkError or RateLimitError)."""
    return isinstance(error, RETRIABLE_ERRORS)


class RetryService:
    """Wraps callable operations with configurable retry logic for transient failures."""

    def __init__(
        self,
        max_attempts: int = 3,
    ):
        """Initialize with max_attempts (must be >= 1).

        Raises:
            ValueError: If max_attempts < 1.
        """
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got: {max_attempts}")

        self.max_attempts = max_attempts

    def execute(
        self,
        operation: Callable[[], Any],
        context: str | None = None,
    ) -> RetryResult:
        """Execute an operation with retry logic.

        Raises:
            Exception: Re-raises non-retriable errors immediately.
        """
        last_error: Exception | None = None
        reason: str | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = operation()
                return RetryResult(
                    response=response,
                    attempts=attempt,
                    reason=reason,  # Set if we retried before succeeding
                    exhausted=False,
                    last_error=str(last_error) if last_error else None,
                )

            except Exception as e:
                last_error = e
                reason = classify_error(e)

                if is_retriable_error(e):
                    log_context = f" ({context})" if context else ""
                    if attempt < self.max_attempts:
                        logger.info(
                            "Retry attempt %d/%d%s: %s - %s",
                            attempt,
                            self.max_attempts,
                            log_context,
                            reason,
                            str(e),
                        )
                        continue
                    else:
                        logger.warning(
                            "Retry exhausted after %d attempts%s: %s - %s",
                            attempt,
                            log_context,
                            reason,
                            str(e),
                        )
                        fire_event(
                            RetryExhaustedEvent(
                                attempt=attempt,
                                max_attempts=self.max_attempts,
                                reason=reason,
                                error=str(e),
                            )
                        )
                else:
                    logger.error(
                        "Non-retriable error%s: %s",
                        f" ({context})" if context else "",
                        str(e),
                    )
                    raise

        return RetryResult(
            response=None,
            attempts=self.max_attempts,
            reason=reason,
            exhausted=True,
            last_error=str(last_error) if last_error else None,
        )


def create_retry_service_from_config(
    retry_config: dict | None,
) -> RetryService | None:
    """Create a RetryService from action config, or return None if not enabled."""
    if retry_config is None:
        return None

    if not retry_config.get("enabled", True):
        return None

    return RetryService(
        max_attempts=retry_config.get("max_attempts", 3),
    )
