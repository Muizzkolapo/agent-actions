"""
Recovery engine for retry.

Handles transient error recovery (rate limits, network issues) with exponential backoff.
"""

import logging
import time
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from agent_actions.recovery.recovery_config import (
    RecoveryConfig,
    RecoveryMode,
    ExhaustedBehavior,
    RetryConfig,
)
from agent_actions.errors import RateLimitError, NetworkError

logger = logging.getLogger(__name__)


@dataclass
class RecoveryResult:
    """Result of a recovery attempt.

    Attributes:
        success: Whether the operation succeeded
        response: The response data (if success or partial)
        mode: Which recovery mode was used (retry)
        attempts: Number of attempts made
        exhausted: Whether max attempts were reached
        error: Last error message (if failed)
    """

    success: bool
    response: Any = None
    mode: Optional[RecoveryMode] = None
    attempts: int = 0
    exhausted: bool = False
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class RecoveryEngine:
    """Recovery engine for transient errors.

    Handles retry with exponential backoff for rate limits and network issues.

    Usage:
        config = RecoveryConfig.from_yaml(retry=True)
        engine = RecoveryEngine(config)

        result = engine.execute_with_recovery(
            invoke_fn=lambda: client.call(...),
            context={'action': 'extract_facts', 'record': {...}}
        )
    """

    def __init__(
        self,
        config: RecoveryConfig,
    ):
        """Initialize recovery engine.

        Args:
            config: RecoveryConfig instance
        """
        self.recovery_config = config

    def execute_with_recovery(
        self,
        invoke_fn: Callable[[], Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> RecoveryResult:
        """Execute an operation with retry recovery.

        Args:
            invoke_fn: Function that performs the LLM call. Called with no args,
                       should return response data.
            context: Context for tracking (action name, record data, etc.)

        Returns:
            RecoveryResult with success status and response
        """
        context = context or {}
        action_name = context.get("action", "unknown")
        record = context.get("record", {})

        retry_config = self.recovery_config.retry

        last_error = None
        last_response = None

        # Retry loop for transient errors
        retry_attempt = 0
        max_attempts = retry_config.max_attempts if retry_config.enabled else 1

        while retry_attempt < max_attempts:
            retry_attempt += 1

            try:
                # Invoke the LLM
                response = invoke_fn()
                last_response = response

                # Success!
                return RecoveryResult(
                    success=True,
                    response=response,
                    attempts=retry_attempt,
                )

            except (RateLimitError, NetworkError) as e:
                last_error = str(e)
                logger.debug(f"Transient error (attempt {retry_attempt}): {e}")

                if retry_attempt < max_attempts:
                    # Calculate backoff
                    delay = self._calculate_backoff(
                        retry_attempt,
                        retry_config.backoff_base,
                        retry_config.backoff_max,
                        e,
                    )
                    logger.info(f"Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                    continue

                # Exhausted retry attempts
                return self._handle_exhausted(
                    config=retry_config,
                    response=last_response,
                    error=last_error,
                    attempts=retry_attempt,
                    context=context,
                )

        # Should not reach here
        return RecoveryResult(
            success=False,
            response=last_response,
            error=last_error,
            attempts=retry_attempt,
        )

    def _calculate_backoff(
        self,
        attempt: int,
        base: float,
        max_delay: float,
        error: Optional[Exception] = None,
    ) -> float:
        """Calculate exponential backoff with jitter.

        Args:
            attempt: Current attempt number
            base: Base delay in seconds
            max_delay: Maximum delay in seconds
            error: The error (may contain retry_after)

        Returns:
            Delay in seconds
        """
        # Check for retry_after header
        if error and hasattr(error, "context"):
            retry_after = error.context.get("retry_after")
            if retry_after:
                return min(float(retry_after), max_delay)

        # Exponential backoff: base * 2^(attempt-1)
        delay = base * (2 ** (attempt - 1))

        # Add jitter (0-25%)
        jitter = delay * random.uniform(0, 0.25)
        delay += jitter

        return min(delay, max_delay)

    def _handle_exhausted(
        self,
        config: RetryConfig,
        response: Any,
        error: str,
        attempts: int,
        context: Dict[str, Any],
    ) -> RecoveryResult:
        """Handle exhausted recovery attempts.

        Args:
            config: The retry config
            response: Last response
            error: Last error
            attempts: Total attempts made
            context: Context for error messages

        Returns:
            RecoveryResult based on on_exhausted behavior
        """
        action = context.get("action", "unknown")
        behavior = config.on_exhausted

        logger.warning(
            f"Retry exhausted for {action}: attempts={attempts}, behavior={behavior.value}"
        )

        if behavior == ExhaustedBehavior.FAIL:
            from agent_actions.errors import ProcessingError

            raise ProcessingError(
                f"Retry exhausted after {attempts} attempts: {error}",
                context={"action": action, "attempts": attempts},
            )

        # CONTINUE - return result for caller to handle
        return RecoveryResult(
            success=False,
            response=response,
            mode=RecoveryMode.RETRY,
            attempts=attempts,
            exhausted=True,
            error=error,
            metadata={
                "on_exhausted": behavior.value,
                "action": action,
            },
        )
