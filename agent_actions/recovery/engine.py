"""
Unified recovery engine for retry and reprompt.

Orchestrates error recovery for both:
- Transient errors (rate limits, network) -> retry with backoff
- Validation errors (bad JSON, schema) -> reprompt with feedback
"""

import logging
import time
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from agent_actions.recovery.config import (
    RecoveryConfig,
    RecoveryMode,
    ExhaustedBehavior,
)
from agent_actions.errors import RateLimitError, NetworkError

logger = logging.getLogger(__name__)


@dataclass
class RecoveryResult:
    """Result of a recovery attempt.

    Attributes:
        success: Whether the operation succeeded
        response: The response data (if success or partial)
        mode: Which recovery mode was used (retry/reprompt)
        attempts: Number of attempts made
        exhausted: Whether max attempts were reached
        error: Last error message (if failed)
        repair_method: JSON repair method used (if any)
    """

    success: bool
    response: Any = None
    mode: Optional[RecoveryMode] = None
    attempts: int = 0
    exhausted: bool = False
    error: Optional[str] = None
    repair_method: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class RecoveryEngine:
    """Unified recovery engine for transient and validation errors.

    Usage:
        config = RecoveryConfig.from_yaml(retry=True, reprompt='smart')
        engine = RecoveryEngine(config)

        # Execute with recovery
        result = engine.execute_with_recovery(
            invoke_fn=lambda: client.call(...),
            validate_fn=lambda resp: schema.validate(resp),
            build_reprompt_fn=lambda resp, err: f"Fix this: {err}",
            context={'action': 'extract_facts', 'record': {...}}
        )
    """

    def __init__(
        self,
        config: RecoveryConfig,
        tracker: Optional[Any] = None,  # RetryTracker instance
    ):
        """Initialize recovery engine.

        Args:
            config: RecoveryConfig instance
            tracker: Optional RetryTracker for logging events
        """
        self.config = config
        self.tracker = tracker

        # Lazy import JSON repair to avoid circular deps
        self._json_repair = None

    @property
    def json_repair(self):
        """Lazy load JSON repair strategy."""
        if self._json_repair is None:
            from agent_actions.reprompting.json_repair import JSONRepairStrategy

            self._json_repair = JSONRepairStrategy()
        return self._json_repair

    def execute_with_recovery(
        self,
        invoke_fn: Callable[[], Any],
        validate_fn: Optional[Callable[[Any], tuple]] = None,
        build_reprompt_fn: Optional[Callable[[Any, str, int], str]] = None,
        context: Optional[Dict[str, Any]] = None,
        json_mode: bool = True,
    ) -> RecoveryResult:
        """Execute an operation with unified recovery.

        Args:
            invoke_fn: Function that performs the LLM call. Called with no args,
                       should return response data.
            validate_fn: Function to validate response. Returns (is_valid, error_msg).
                        If None, no validation is performed.
            build_reprompt_fn: Function to build reprompt. Args: (response, error, attempt).
                              Returns modified prompt string.
            context: Context for tracking (action name, record data, etc.)
            json_mode: Whether JSON output is expected (enables JSON repair)

        Returns:
            RecoveryResult with success status and response
        """
        context = context or {}
        action_name = context.get("action", "unknown")
        record = context.get("record", {})

        retry_config = self.config.retry
        reprompt_config = self.config.reprompt

        total_attempts = 0
        last_error = None
        last_response = None
        repair_method = None

        # Outer loop: retry for transient errors
        retry_attempt = 0
        while retry_attempt < retry_config.max_attempts if retry_config.enabled else 1:
            retry_attempt += 1

            try:
                # Inner loop: reprompt for validation errors
                reprompt_attempt = 0
                current_prompt_modifier = None

                while (
                    reprompt_attempt < reprompt_config.max_attempts
                    if reprompt_config.enabled
                    else 1
                ):
                    reprompt_attempt += 1
                    total_attempts += 1

                    try:
                        # Invoke the LLM
                        response = invoke_fn()
                        last_response = response

                        # JSON repair if enabled
                        if json_mode and reprompt_config.json_repair:
                            response, repair_method = self._try_json_repair(response)
                            if repair_method:
                                logger.debug(f"JSON repaired using: {repair_method}")

                        # Validation if provided
                        if validate_fn:
                            is_valid, error_msg = validate_fn(response)
                            if not is_valid:
                                last_error = error_msg
                                logger.debug(
                                    f"Validation failed (attempt {reprompt_attempt}): {error_msg}"
                                )

                                # Log reprompt event
                                self._log_event(
                                    mode=RecoveryMode.REPROMPT,
                                    action=action_name,
                                    attempt=reprompt_attempt,
                                    max_attempts=reprompt_config.max_attempts,
                                    error=error_msg,
                                    record=record,
                                )

                                # Build reprompt if we have more attempts
                                if (
                                    reprompt_attempt < reprompt_config.max_attempts
                                    and build_reprompt_fn
                                ):
                                    current_prompt_modifier = build_reprompt_fn(
                                        response, error_msg, reprompt_attempt
                                    )
                                    continue

                                # Exhausted reprompt attempts
                                break

                        # Success!
                        self._mark_success(action_name)
                        return RecoveryResult(
                            success=True,
                            response=response,
                            mode=RecoveryMode.REPROMPT if reprompt_attempt > 1 else None,
                            attempts=total_attempts,
                            repair_method=repair_method,
                        )

                    except (RateLimitError, NetworkError):
                        # Let outer retry loop handle these
                        raise

                # Reprompt exhausted
                if reprompt_config.enabled and reprompt_attempt >= reprompt_config.max_attempts:
                    return self._handle_exhausted(
                        mode=RecoveryMode.REPROMPT,
                        config=reprompt_config,
                        response=last_response,
                        error=last_error,
                        attempts=total_attempts,
                        context=context,
                    )

                # No validation or validation passed
                return RecoveryResult(
                    success=True,
                    response=last_response,
                    attempts=total_attempts,
                )

            except (RateLimitError, NetworkError) as e:
                last_error = str(e)
                logger.debug(f"Transient error (attempt {retry_attempt}): {e}")

                # Log retry event
                self._log_event(
                    mode=RecoveryMode.RETRY,
                    action=action_name,
                    attempt=retry_attempt,
                    max_attempts=retry_config.max_attempts,
                    error=str(e),
                    record=record,
                    error_type=type(e).__name__,
                )

                if retry_attempt < retry_config.max_attempts:
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
                    mode=RecoveryMode.RETRY,
                    config=retry_config,
                    response=last_response,
                    error=last_error,
                    attempts=total_attempts,
                    context=context,
                )

        # Should not reach here
        return RecoveryResult(
            success=False,
            response=last_response,
            error=last_error,
            attempts=total_attempts,
        )

    def _try_json_repair(self, response: Any) -> tuple:
        """Attempt JSON repair on response.

        Returns:
            Tuple of (repaired_response, repair_method)
        """
        if isinstance(response, (dict, list)):
            return response, None

        if isinstance(response, str):
            result = self.json_repair.attempt_repair(response)
            if result.success:
                return result.data, result.repair_method
            return response, None

        return response, None

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

    def _log_event(
        self,
        mode: RecoveryMode,
        action: str,
        attempt: int,
        max_attempts: int,
        error: str,
        record: Any,
        error_type: str = "ValidationError",
    ) -> None:
        """Log recovery event to tracker."""
        if self.tracker:
            self.tracker.log_retry(
                action=action,
                mode=mode.value,
                attempt=attempt,
                max_attempts=max_attempts,
                error_type=error_type,
                error_message=error,
                record=record,
            )

    def _mark_success(self, action: str) -> None:
        """Mark the last event as successful."""
        # Tracker handles this internally
        pass

    def _handle_exhausted(
        self,
        mode: RecoveryMode,
        config: Union["RetryConfig", "RepromptConfig"],
        response: Any,
        error: str,
        attempts: int,
        context: Dict[str, Any],
    ) -> RecoveryResult:
        """Handle exhausted recovery attempts.

        Args:
            mode: Which recovery mode exhausted
            config: The config (retry or reprompt)
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
            f"Recovery exhausted for {action}: mode={mode.value}, "
            f"attempts={attempts}, behavior={behavior.value}"
        )

        if behavior == ExhaustedBehavior.FAIL:
            from agent_actions.errors import ProcessingError

            raise ProcessingError(
                f"{mode.value.title()} exhausted after {attempts} attempts: {error}",
                context={"action": action, "mode": mode.value, "attempts": attempts},
            )

        # CONTINUE or DEAD_LETTER - return result for caller to handle
        return RecoveryResult(
            success=False,
            response=response,
            mode=mode,
            attempts=attempts,
            exhausted=True,
            error=error,
            metadata={
                "on_exhausted": behavior.value,
                "action": action,
            },
        )
