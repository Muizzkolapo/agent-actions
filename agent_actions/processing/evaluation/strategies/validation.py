"""ValidationStrategy — wraps reprompt validation as an EvaluationStrategy."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agent_actions.processing.helpers import get_parse_error_marker
from agent_actions.processing.recovery.response_validator import (
    build_validation_feedback,
    safe_validate,
)
from agent_actions.processing.types import EvaluationOutcome
from agent_actions.utils.schema_echo import is_schema_echo

if TYPE_CHECKING:
    from collections.abc import Callable

    from agent_actions.llm.providers.batch_base import BatchResult
    from agent_actions.processing.recovery.response_validator import FeedbackStrategy

logger = logging.getLogger(__name__)

_PARSE_ERROR_FEEDBACK = (
    "---\n"
    "Your previous response was not valid JSON and could not be parsed.\n"
    "Please respond with a valid JSON object only — no preamble, no markdown fences."
)


def detect_parse_error(content: Any, *, json_mode: bool) -> str | None:
    """Detect a parse error in batch result content.

    Batch providers return content as a raw string when JSON parsing fails.
    Online providers wrap as ``{"_parse_error": "..."}``.  This helper checks
    both patterns.
    """
    # String content in json_mode = provider couldn't parse JSON
    if json_mode and isinstance(content, str):
        return "Failed to parse JSON from LLM response"
    # Dict/list with _parse_error marker (shared with reprompt path)
    marker = get_parse_error_marker(content)
    if marker is not None:
        return marker
    # Schema-echo: LLM returned the JSON Schema definition instead of data
    if is_schema_echo(content):
        return "Schema-echo: LLM returned the schema definition instead of conforming data"
    return None


class ValidationStrategy:
    """Reprompt validation as an EvaluationStrategy."""

    def __init__(
        self,
        validation_func: Callable[[Any], bool],
        feedback_message: str,
        strategies: list[FeedbackStrategy] | None = None,
        max_attempts: int = 3,
        on_exhausted: str = "return_last",
        json_mode: bool = False,
        validation_name: str = "validation",
    ) -> None:
        self._validation_func = validation_func
        self._feedback_message = feedback_message
        self._strategies = strategies
        self._max_attempts = max_attempts
        self._on_exhausted = on_exhausted
        self._json_mode = json_mode
        self._validation_name = validation_name

    @property
    def name(self) -> str:
        return self._validation_name

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    @property
    def on_exhausted(self) -> str:
        return self._on_exhausted

    def evaluate(self, result: BatchResult) -> EvaluationOutcome:
        """Return evaluation outcome with failure classification."""
        if not result.success:
            return EvaluationOutcome(passed=False, failure_type="api_error", error=result.error)

        if (
            result.recovery_metadata
            and result.recovery_metadata.reprompt
            and result.recovery_metadata.reprompt.passed
        ):
            return EvaluationOutcome(passed=True)

        parse_error = detect_parse_error(result.content, json_mode=self._json_mode)
        if parse_error:
            logger.warning(
                "Parse error detected for %s before UDF: %s",
                result.custom_id,
                parse_error,
            )
            return EvaluationOutcome(passed=False, failure_type="parse_error", error=parse_error)

        if safe_validate(
            self._validation_func,
            result.content,
            context=result.custom_id,
            catch=(Exception,),
        ):
            return EvaluationOutcome(passed=True)

        return EvaluationOutcome(passed=False, failure_type="udf_fail")

    def build_feedback(self, result: BatchResult) -> str:
        """Build validation feedback for a failing result."""
        if not result.success:
            return (
                "---\n"
                "The previous attempt failed due to an API error and produced no response.\n"
                "Please respond again."
            )

        # Parse error → JSON-specific feedback (not generic UDF feedback)
        if detect_parse_error(result.content, json_mode=self._json_mode):
            return _PARSE_ERROR_FEEDBACK

        return build_validation_feedback(
            failed_response=result.content,
            feedback_message=self._feedback_message,
            strategies=self._strategies,
        )
