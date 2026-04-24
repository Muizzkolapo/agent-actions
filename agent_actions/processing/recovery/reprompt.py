"""Reprompt service for validation-based LLM recovery."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.validation_events import RepromptValidationFailedEvent

from .critique import format_critique_feedback
from .response_validator import (
    FeedbackStrategy,
    UdfValidator,
    build_validation_feedback,
    resolve_feedback_strategies,
    safe_validate,
)
from .retry import RetryExhaustedException

if TYPE_CHECKING:
    from collections.abc import Callable

    from .response_validator import ResponseValidator

logger = logging.getLogger(__name__)


@dataclass
class RepromptResult:
    """Result of reprompt execution."""

    response: Any | None  # The actual LLM response content
    executed: bool  # Whether LLM was executed (False if guard skipped)
    attempts: int
    passed: bool  # Whether validation ultimately passed
    validation_name: str
    exhausted: bool = False


@dataclass
class ParsedRepromptConfig:
    """Validated reprompt settings extracted from a raw config dict."""

    validation_name: str
    max_attempts: int = 2
    on_exhausted: str = "return_last"


def parse_reprompt_config(reprompt_config: dict | None) -> ParsedRepromptConfig | None:
    """Parse a raw reprompt config dict into validated settings.

    Returns ``None`` if *reprompt_config* is empty or has no ``validation`` key.
    """
    if not reprompt_config:
        return None
    validation_name = reprompt_config.get("validation")
    if not validation_name:
        return None
    return ParsedRepromptConfig(
        validation_name=validation_name,
        max_attempts=reprompt_config.get("max_attempts", 2),
        on_exhausted=reprompt_config.get("on_exhausted", "return_last"),
    )


class RepromptService:
    """Wraps LLM execution with a validate-and-reprompt loop."""

    def __init__(
        self,
        validation_name: str = "",
        max_attempts: int = 2,
        on_exhausted: str = "return_last",
        validator: ResponseValidator | None = None,
        strategies: list[FeedbackStrategy] | None = None,
        critique_fn: Callable[[Any, str], str] | None = None,
        critique_after_attempt: int = 2,
    ):
        """Initialize with either a ``validation_name`` or a pre-built ``validator``.

        Args:
            critique_fn: Optional callable that takes (response, validation_errors)
                and returns critique analysis text. When provided, critique fires
                on attempts after ``critique_after_attempt``.
            critique_after_attempt: Attempt threshold before critique fires
                (critique starts on attempt N+1). Default: 2.

        Raises:
            ValueError: If neither validation source is provided,
                       max_attempts < 1, or on_exhausted is invalid.
        """
        if validator is None and (not validation_name or not validation_name.strip()):
            raise ValueError("validation_name cannot be empty")

        if max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got: {max_attempts}")

        valid_exhausted_options = ("return_last", "raise")
        if on_exhausted not in valid_exhausted_options:
            raise ValueError(
                f"on_exhausted must be one of {valid_exhausted_options}, got: '{on_exhausted}'"
            )

        self.max_attempts = max_attempts
        self.on_exhausted = on_exhausted
        self._critique_fn = critique_fn
        self._critique_after_attempt = critique_after_attempt

        if validator is not None:
            self._validator = validator
            self.validation_name = validator.name
        else:
            self._validator = UdfValidator(validation_name)
            self.validation_name = validation_name

        self.validation_func = self._validator.validate
        self._strategies = strategies or []

    @property
    def feedback_message(self) -> str:
        """Delegate to validator for always-current feedback message."""
        return self._validator.feedback_message

    def execute(
        self,
        llm_operation: Callable[[str], tuple[Any, bool]],
        original_prompt: str,
        context: str = "",
        on_exhausted: str | None = None,
    ) -> RepromptResult:
        """Execute LLM with reprompt loop until validation passes or attempts exhausted.

        Raises:
            RuntimeError: If on_exhausted="raise" and validation exhausted.
        """
        exhausted_behavior = on_exhausted if on_exhausted is not None else self.on_exhausted

        valid_exhausted_options = ("return_last", "raise")
        if exhausted_behavior not in valid_exhausted_options:
            raise ValueError(
                f"on_exhausted must be one of {valid_exhausted_options}, got: '{exhausted_behavior}'"
            )

        attempts = 0
        current_prompt = original_prompt
        last_response = None

        while attempts < self.max_attempts:
            attempts += 1

            try:
                response, executed = llm_operation(current_prompt)
            except RetryExhaustedException as exc:
                logger.warning(
                    "[%s] Retry exhausted on reprompt attempt %d/%d: %s",
                    context,
                    attempts,
                    self.max_attempts,
                    exc.retry_result.last_error,
                )
                if exhausted_behavior == "raise":
                    raise RuntimeError(
                        f"Retry exhausted during reprompt attempt {attempts}/{self.max_attempts}: "
                        f"{exc.retry_result.last_error}"
                    ) from exc
                return RepromptResult(
                    response=last_response,
                    executed=True,
                    attempts=attempts,
                    passed=False,
                    validation_name=self.validation_name,
                    exhausted=True,
                )

            if not executed:
                logger.info("[%s] Guard skipped execution, bypassing reprompt", context)
                return RepromptResult(
                    response=response,
                    executed=False,
                    attempts=0,  # No validation attempts
                    passed=True,  # Treat as pass
                    validation_name=self.validation_name,
                    exhausted=False,
                )

            last_response = response

            is_valid = safe_validate(self._validator.validate, response, context=context)

            if is_valid:
                logger.info(
                    "[%s] Validation passed on attempt %d/%d",
                    context,
                    attempts,
                    self.max_attempts,
                )
                return RepromptResult(
                    response=response,
                    executed=True,
                    attempts=attempts,
                    passed=True,
                    validation_name=self.validation_name,
                    exhausted=False,
                )

            logger.warning(
                "[%s] Validation failed on attempt %d/%d",
                context,
                attempts,
                self.max_attempts,
            )

            if attempts >= self.max_attempts:
                break

            feedback = build_validation_feedback(
                response, self._validator.feedback_message, strategies=self._strategies
            )

            if self._critique_fn is not None and attempts >= self._critique_after_attempt:
                try:
                    critique_text = self._critique_fn(response, self._validator.feedback_message)
                    feedback = format_critique_feedback(critique_text, feedback)
                    logger.info(
                        "[%s] LLM critique appended to reprompt feedback (attempt %d)",
                        context,
                        attempts,
                    )
                except Exception:
                    logger.warning(
                        "[%s] LLM critique call failed, continuing without critique",
                        context,
                        exc_info=True,
                    )

            current_prompt = f"{original_prompt}\n\n{feedback}"

        logger.error(
            "[%s] Reprompt exhausted after %d attempts (validation: %s)",
            context,
            attempts,
            self.validation_name,
        )
        fire_event(
            RepromptValidationFailedEvent(
                action_name=context or "NOT_SET",
                attempt=attempts,
                error=f"Validation '{self.validation_name}' failed after {attempts} attempts",
            )
        )

        if exhausted_behavior == "raise":
            raise RuntimeError(
                f"Reprompt validation exhausted after {attempts} attempts "
                f"(validation: {self.validation_name})"
            )

        return RepromptResult(
            response=last_response,
            executed=True,  # LLM was executed, validation just failed
            attempts=attempts,
            passed=False,
            validation_name=self.validation_name,
            exhausted=True,
        )


def create_reprompt_service_from_config(
    reprompt_config: dict | None,
    validator: ResponseValidator | None = None,
    critique_fn: Callable[[Any, str], str] | None = None,
) -> RepromptService | None:
    """Create RepromptService from action config, or return None if not enabled.

    Args:
        reprompt_config: Reprompt configuration dict from agent_config.
        validator: Pre-built validator (e.g. SchemaValidator).
        critique_fn: Optional critique callable, wired by the factory when
            ``use_llm_critique`` is enabled.

    Raises:
        ValueError: If required 'validation' key is missing and no validator provided.
    """
    parsed = parse_reprompt_config(reprompt_config)
    strategies = resolve_feedback_strategies(reprompt_config)

    if parsed is None:
        if validator is not None:
            # External validator provided but no validation key -- still respect
            # other config settings (max_attempts, on_exhausted) if present.
            cfg = reprompt_config or {}
            return RepromptService(
                max_attempts=cfg.get("max_attempts", 2),
                on_exhausted=cfg.get("on_exhausted", "return_last"),
                validator=validator,
                strategies=strategies,
                critique_fn=critique_fn,
                critique_after_attempt=cfg.get("critique_after_attempt", 2),
            )
        if reprompt_config:
            raise ValueError(
                "Reprompt configuration missing required 'validation' field. "
                "Example: {'validation': 'check_no_forbidden_words', 'max_attempts': 2}"
            )
        return None

    return RepromptService(
        validation_name=parsed.validation_name,
        max_attempts=parsed.max_attempts,
        on_exhausted=parsed.on_exhausted,
        validator=validator,
        strategies=strategies,
        critique_fn=critique_fn,
        critique_after_attempt=(reprompt_config or {}).get("critique_after_attempt", 2),
    )
