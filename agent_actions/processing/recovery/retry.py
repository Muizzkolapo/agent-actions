"""
Retry Service for handling transport-layer failures.

This module provides retry logic for LLM calls in both online and batch modes.
It wraps operations with configurable retry behavior and tracks recovery metadata.
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

from agent_actions.errors import NetworkError, RateLimitError, VendorAPIError
from agent_actions.logging import fire_event
from agent_actions.logging.events.types import RetryExhaustedEvent

logger = logging.getLogger(__name__)

T = TypeVar("T")


# Errors that should trigger a retry
RETRIABLE_ERRORS = (NetworkError, RateLimitError)


@dataclass
class RetryResult:
    """
    Result of a retry-wrapped operation.

    Attributes:
        response: The successful response (or last response if exhausted)
        attempts: Number of attempts made (1 = no retry needed)
        reason: Reason for retry if any occurred (None if no retry needed)
        exhausted: Whether max attempts were exhausted without success
        last_error: The last error encountered (if any)
    """

    response: Any
    attempts: int = 1
    reason: Optional[str] = None
    exhausted: bool = False
    last_error: Optional[str] = None

    @property
    def needed_retry(self) -> bool:
        """Return True if retry was triggered (attempts > 1) or exhausted on first attempt."""
        return self.attempts > 1 or self.exhausted


def classify_error(error: Exception) -> str:
    """
    Classify an error for retry reason tracking.

    Args:
        error: The exception to classify

    Returns:
        Reason string: "timeout", "rate_limit", "api_error", or "network_error"
    """
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
    """
    Check if an error should trigger a retry.

    Args:
        error: The exception to check

    Returns:
        True if the error is retriable, False otherwise
    """
    return isinstance(error, RETRIABLE_ERRORS)


class RetryService:
    """
    Service for executing operations with retry logic.

    This service wraps callable operations and retries them on transient failures.
    It tracks retry attempts and provides metadata for the _recovery field.

    Example:
        retry_service = RetryService(max_attempts=3, on_exhausted="return_last")

        result = retry_service.execute(
            lambda: llm_client.call(prompt),
        )

        if result.needed_retry:
            print(f"Retried {result.attempts} times due to {result.reason}")
    """

    def __init__(
        self,
        max_attempts: int = 3,
        on_exhausted: str = "return_last",
    ):
        """
        Initialize the RetryService.

        Args:
            max_attempts: Maximum number of attempts (1 = no retry)
            on_exhausted: Behavior when exhausted: "return_last" or "raise"
        """
        self.max_attempts = max(1, max_attempts)
        self.on_exhausted = on_exhausted

    def execute(
        self,
        operation: Callable[[], T],
        context: Optional[str] = None,
    ) -> RetryResult:
        """
        Execute an operation with retry logic.

        Args:
            operation: A callable that performs the operation (e.g., LLM call)
            context: Optional context string for logging

        Returns:
            RetryResult containing the response and retry metadata

        Raises:
            Exception: Re-raises the last exception if on_exhausted="raise" and exhausted
        """
        last_response = None
        last_error: Optional[Exception] = None
        reason: Optional[str] = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = operation()
                # Success - return with retry metadata if we retried
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
                last_response = None  # Clear any partial response

                if is_retriable_error(e):
                    # Retriable error - log and retry
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
                        # Exhausted retries
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
                    # Non-retriable error - don't retry, re-raise immediately
                    logger.error(
                        "Non-retriable error%s: %s",
                        f" ({context})" if context else "",
                        str(e),
                    )
                    raise

        # Exhausted all retries - always return result, let caller decide whether to raise
        # The on_exhausted config is just stored in self.on_exhausted for reference
        # but the actual decision to raise is made by the higher-level code
        return RetryResult(
            response=last_response,
            attempts=self.max_attempts,
            reason=reason,
            exhausted=True,
            last_error=str(last_error) if last_error else None,
        )


def create_retry_service_from_config(retry_config: Optional[dict]) -> Optional[RetryService]:
    """
    Create a RetryService from action configuration.

    Args:
        retry_config: The retry configuration dict from action config.
                     Expected format: {"enabled": bool, "max_attempts": int, "on_exhausted": str}

    Returns:
        RetryService if retry is enabled, None otherwise
    """
    if retry_config is None:
        return None

    if not retry_config.get("enabled", True):
        return None

    return RetryService(
        max_attempts=retry_config.get("max_attempts", 3),
        on_exhausted=retry_config.get("on_exhausted", "return_last"),
    )
