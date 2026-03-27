"""Reprompt service for validation-based LLM recovery."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agent_actions.logging import fire_event
from agent_actions.logging.events.validation_events import RepromptValidationFailedEvent

from .response_validator import UdfValidator, build_validation_feedback

if TYPE_CHECKING:
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


class RepromptService:
    """Wraps LLM execution with a validate-and-reprompt loop."""

    def __init__(
        self,
        validation_name: str = "",
        max_attempts: int = 2,
        on_exhausted: str = "return_last",
        validator: ResponseValidator | None = None,
    ):
        """Initialize with either a ``validation_name`` or a pre-built ``validator``.

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

        if validator is not None:
            self._validator = validator
        else:
            self._validator = UdfValidator(validation_name)

        if validator is not None:
            self.validation_name = self._validator.name
        else:
            self.validation_name = validation_name

        self.validation_func = self._validator.validate

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

            response, executed = llm_operation(current_prompt)

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

            try:
                is_valid = self._validator.validate(response)
            except (ValueError, TypeError, LookupError) as e:
                logger.warning(
                    "[%s] Validation '%s' raised exception "
                    "(treating as validation failure): %s: %s",
                    context,
                    self.validation_name,
                    e.__class__.__name__,
                    e,
                    exc_info=True,
                )
                is_valid = False

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

            feedback = build_validation_feedback(response, self._validator.feedback_message)
            current_prompt = f"{original_prompt}\n\n{feedback}"

        logger.error(
            "[%s] Reprompt exhausted after %d attempts (validation: %s)",
            context,
            attempts,
            self.validation_name,
        )
        fire_event(
            RepromptValidationFailedEvent(
                action_name=context or "unknown",
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
) -> RepromptService | None:
    """Create RepromptService from action config, or return None if not enabled.

    Raises:
        ValueError: If required 'validation' key is missing and no validator provided.
    """
    if not reprompt_config:
        if validator is not None:
            return RepromptService(validator=validator)
        return None

    if validator is None and "validation" not in reprompt_config:
        raise ValueError(
            "Reprompt configuration missing required 'validation' field. "
            "Example: {'validation': 'check_no_forbidden_words', 'max_attempts': 2}"
        )

    return RepromptService(
        validation_name=reprompt_config.get("validation", ""),
        max_attempts=reprompt_config.get("max_attempts", 2),
        on_exhausted=reprompt_config.get("on_exhausted", "return_last"),
        validator=validator,
    )
