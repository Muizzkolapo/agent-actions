"""
Reprompt service for validation-based recovery.

Validates LLM responses using UDFs and re-executes with feedback
when validation fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any, Optional, Tuple, Dict, TYPE_CHECKING
import logging

from agent_actions.logging import fire_event
from agent_actions.logging.events.types import RepromptValidationFailedEvent
from .response_validator import UdfValidator, build_validation_feedback

if TYPE_CHECKING:
    from .response_validator import ResponseValidator

logger = logging.getLogger(__name__)


@dataclass
class RepromptResult:
    """Result of reprompt execution."""

    response: Any  # The actual LLM response content
    executed: bool  # Whether LLM was executed (False if guard skipped)
    attempts: int
    passed: bool  # Whether validation ultimately passed
    validation_name: str
    exhausted: bool = False


class RepromptService:
    """
    Service for validating and reprompting LLM responses.

    Wraps LLM execution with validation loop:
    1. Execute LLM
    2. Validate response with UDF
    3. If fails, append feedback and re-execute
    4. Repeat until pass or max_attempts exhausted
    """

    def __init__(
        self,
        validation_name: str = "",
        max_attempts: int = 2,
        on_exhausted: str = "return_last",
        validator: Optional[ResponseValidator] = None,
    ):
        """
        Initialize reprompt service.

        Accepts either a ``validation_name`` (legacy -- wraps in ``UdfValidator``)
        or a pre-built ``validator`` implementing the ``ResponseValidator`` protocol.
        At least one must be provided.

        Args:
            validation_name: Name of validation UDF (legacy path)
            max_attempts: Maximum reprompt attempts (default: 2)
            on_exhausted: Behavior when exhausted ("return_last" | "raise")
            validator: Pre-built ResponseValidator (preferred path)

        Raises:
            ValueError: If neither validation_name nor validator provided,
                       max_attempts < 1, or on_exhausted is invalid
        """
        # Must have at least one validation source
        if validator is None and (not validation_name or not validation_name.strip()):
            raise ValueError("validation_name cannot be empty")

        # Validate max_attempts
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got: {max_attempts}")

        # Validate on_exhausted
        valid_exhausted_options = ("return_last", "raise")
        if on_exhausted not in valid_exhausted_options:
            raise ValueError(
                f"on_exhausted must be one of {valid_exhausted_options}, got: '{on_exhausted}'"
            )

        self.max_attempts = max_attempts
        self.on_exhausted = on_exhausted

        # Build validator -- prefer explicit validator, fall back to UDF lookup
        if validator is not None:
            self._validator = validator
        else:
            self._validator = UdfValidator(validation_name)

        # When a validator is explicitly provided, use its name so composed
        # validators (e.g. "check_positive+schema:my_action") are accurately
        # reported in metadata and error messages.
        if validator is not None:
            self.validation_name = self._validator.name
        else:
            self.validation_name = validation_name

        # Backward-compat attributes used by existing code / tests
        self.validation_func = self._validator.validate
        self.feedback_message = self._validator.feedback_message

    def execute(
        self,
        llm_operation: Callable[[str], Tuple[Any, bool]],
        original_prompt: str,
        context: str = "",
        on_exhausted: Optional[str] = None,
    ) -> RepromptResult:
        """
        Execute LLM operation with reprompt loop.

        Args:
            llm_operation: Callable that executes LLM with prompt parameter.
                          Signature: (prompt: str) -> (response, executed)
            original_prompt: Original prompt (for appending feedback)
            context: Context string for logging
            on_exhausted: Override on_exhausted behavior (optional)

        Returns:
            RepromptResult with final response and metadata

        Raises:
            RuntimeError: If on_exhausted="raise" and validation exhausted

        Note:
            The llm_operation callable receives the prompt (with feedback appended
            on reprompt attempts) and returns a tuple of (response, executed).
            If executed=False (guard skip), validation is bypassed.
        """
        # Use override or instance default
        exhausted_behavior = on_exhausted or self.on_exhausted

        attempts = 0
        current_prompt = original_prompt
        last_response = None

        while attempts < self.max_attempts:
            attempts += 1

            # Execute LLM with current prompt (may include feedback from previous attempts)
            response, executed = llm_operation(current_prompt)

            # If guard skipped execution, return immediately
            if not executed:
                logger.info(f"[{context}] Guard skipped execution, bypassing reprompt")
                return RepromptResult(
                    response=response,
                    executed=False,
                    attempts=0,  # No validation attempts
                    passed=True,  # Treat as pass
                    validation_name=self.validation_name,
                    exhausted=False,
                )

            last_response = response

            # Validate response
            try:
                is_valid = self._validator.validate(response)
            except Exception as e:
                # Log validator exception with full context and traceback
                # This helps distinguish validator bugs from actual validation failures
                logger.warning(
                    f"[{context}] Validation '{self.validation_name}' raised exception "
                    f"(treating as validation failure): {e.__class__.__name__}: {e}",
                    exc_info=True,
                )
                is_valid = False

            if is_valid:
                logger.info(
                    f"[{context}] Validation passed on attempt {attempts}/{self.max_attempts}"
                )
                return RepromptResult(
                    response=response,
                    executed=True,
                    attempts=attempts,
                    passed=True,
                    validation_name=self.validation_name,
                    exhausted=False,
                )

            # Validation failed
            logger.warning(
                f"[{context}] Validation failed on attempt {attempts}/{self.max_attempts}"
            )

            # Check if exhausted
            if attempts >= self.max_attempts:
                break

            # Prepare feedback message for next attempt
            feedback = build_validation_feedback(response, self._validator.feedback_message)
            current_prompt = f"{original_prompt}\n\n{feedback}"

        # Exhausted all attempts
        logger.error(
            f"[{context}] Reprompt exhausted after {attempts} attempts "
            f"(validation: {self.validation_name})"
        )
        fire_event(
            RepromptValidationFailedEvent(
                agent_name=context or "unknown",
                attempt=attempts,
                error=f"Validation '{self.validation_name}' failed after {attempts} attempts",
            )
        )

        if exhausted_behavior == "raise":
            raise RuntimeError(
                f"Reprompt validation exhausted after {attempts} attempts "
                f"(validation: {self.validation_name})"
            )

        # on_exhausted = "return_last"
        return RepromptResult(
            response=last_response,
            executed=True,  # LLM was executed, validation just failed
            attempts=attempts,
            passed=False,
            validation_name=self.validation_name,
            exhausted=True,
        )

    def _build_feedback_message(self, failed_response: Any) -> str:
        """Build feedback message to append to prompt.

        Thin backward-compat wrapper around ``build_validation_feedback()``.
        """
        return build_validation_feedback(failed_response, self._validator.feedback_message)


def create_reprompt_service_from_config(
    reprompt_config: Optional[Dict],
    validator: Optional[ResponseValidator] = None,
) -> Optional[RepromptService]:
    """
    Create RepromptService from action config.

    Args:
        reprompt_config: Reprompt configuration dict (or None)
        validator: Pre-built ResponseValidator (optional).
                   When provided, ``reprompt_config["validation"]`` is not required.

    Returns:
        RepromptService instance or None if not enabled

    Raises:
        ValueError: If required 'validation' key is missing and no validator provided

    Example:
        config = {
            "validation": "check_no_forbidden_words",
            "max_attempts": 2,
            "on_exhausted": "return_last"
        }
        service = create_reprompt_service_from_config(config)
    """
    if not reprompt_config:
        # Even with a validator, we need reprompt_config for max_attempts etc.
        if validator is not None:
            return RepromptService(validator=validator)
        return None

    # Validate required "validation" key when no validator provided
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
