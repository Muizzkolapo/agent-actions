"""
Reprompt service for validation-based recovery.

Validates LLM responses using UDFs and re-executes with feedback
when validation fails.
"""

from dataclasses import dataclass
from typing import Callable, Any, Optional, Tuple, Dict
import logging
import json

from .reprompt_validation import get_validation_function

logger = logging.getLogger(__name__)


@dataclass
class RepromptResult:
    """Result of reprompt execution."""

    response: Any
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
        validation_name: str,
        max_attempts: int = 2,
        on_exhausted: str = "return_last",
    ):
        """
        Initialize reprompt service.

        Args:
            validation_name: Name of validation UDF
            max_attempts: Maximum reprompt attempts (default: 2)
            on_exhausted: Behavior when exhausted ("return_last" | "raise")

        Raises:
            ValueError: If validation UDF not found
        """
        self.validation_name = validation_name
        self.max_attempts = max_attempts
        self.on_exhausted = on_exhausted

        # Get validation function and feedback message from registry
        self.validation_func, self.feedback_message = get_validation_function(validation_name)

    def execute(
        self,
        llm_operation: Callable[[], Tuple[Any, bool]],
        original_prompt: str,
        context: str = "",
        on_exhausted: Optional[str] = None,
    ) -> RepromptResult:
        """
        Execute LLM operation with reprompt loop.

        Args:
            llm_operation: Callable that executes LLM (returns (response, executed))
            original_prompt: Original prompt (for appending feedback)
            context: Context string for logging
            on_exhausted: Override on_exhausted behavior (optional)

        Returns:
            RepromptResult with final response and metadata

        Raises:
            RuntimeError: If on_exhausted="raise" and validation exhausted

        Note:
            The llm_operation callable should return a tuple of (response, executed).
            If executed=False (guard skip), validation is bypassed.
        """
        # Use override or instance default
        exhausted_behavior = on_exhausted or self.on_exhausted

        attempts = 0
        current_prompt = original_prompt
        last_response = None

        while attempts < self.max_attempts:
            attempts += 1

            # Execute LLM (may return executed=False if guards skip)
            response, executed = llm_operation()

            # If guard skipped execution, return immediately
            if not executed:
                logger.info(f"[{context}] Guard skipped execution, bypassing reprompt")
                return RepromptResult(
                    response=response,
                    attempts=0,  # No validation attempts
                    passed=True,  # Treat as pass
                    validation_name=self.validation_name,
                    exhausted=False,
                )

            last_response = response

            # Validate response
            try:
                is_valid = self.validation_func(response)
            except Exception as e:
                logger.error(f"[{context}] Validation UDF error: {e}")
                is_valid = False

            if is_valid:
                logger.info(
                    f"[{context}] Validation passed on attempt {attempts}/{self.max_attempts}"
                )
                return RepromptResult(
                    response=response,
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
            feedback = self._build_feedback_message(response)
            current_prompt = f"{original_prompt}\n\n{feedback}"

            # TODO: Update llm_operation to use current_prompt for next iteration
            # This requires refactoring how we pass prompts to LLM operations
            # For now, the validation loop continues but prompt is not updated

        # Exhausted all attempts
        logger.error(
            f"[{context}] Reprompt exhausted after {attempts} attempts "
            f"(validation: {self.validation_name})"
        )

        if exhausted_behavior == "raise":
            raise RuntimeError(
                f"Reprompt validation exhausted after {attempts} attempts "
                f"(validation: {self.validation_name})"
            )

        # on_exhausted = "return_last"
        return RepromptResult(
            response=last_response,
            attempts=attempts,
            passed=False,
            validation_name=self.validation_name,
            exhausted=True,
        )

    def _build_feedback_message(self, failed_response: Any) -> str:
        """
        Build feedback message to append to prompt.

        Args:
            failed_response: The response that failed validation

        Returns:
            Formatted feedback message

        Example:
            ---
            Your response failed validation: Response must not contain 'boy'

            Your response: {"description": "A boy and his dog"}

            Please correct and respond again.
        """
        # Format response as JSON for clarity
        try:
            response_str = json.dumps(failed_response, indent=2)
        except Exception:
            response_str = str(failed_response)

        return f"""---
Your response failed validation: {self.feedback_message}

Your response: {response_str}

Please correct and respond again."""


def create_reprompt_service_from_config(
    reprompt_config: Optional[Dict],
) -> Optional[RepromptService]:
    """
    Create RepromptService from action config.

    Args:
        reprompt_config: Reprompt configuration dict (or None)

    Returns:
        RepromptService instance or None if not enabled

    Example:
        config = {
            "validation": "check_no_forbidden_words",
            "max_attempts": 2,
            "on_exhausted": "return_last"
        }
        service = create_reprompt_service_from_config(config)
    """
    if not reprompt_config:
        return None

    return RepromptService(
        validation_name=reprompt_config["validation"],
        max_attempts=reprompt_config.get("max_attempts", 2),
        on_exhausted=reprompt_config.get("on_exhausted", "return_last"),
    )
