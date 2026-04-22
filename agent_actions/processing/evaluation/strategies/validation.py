"""ValidationStrategy — wraps reprompt validation as an EvaluationStrategy."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agent_actions.processing.recovery.response_validator import (
    build_validation_feedback,
    safe_validate,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agent_actions.llm.providers.batch_base import BatchResult
    from agent_actions.processing.recovery.response_validator import FeedbackStrategy

logger = logging.getLogger(__name__)


class ValidationStrategy:
    """Reprompt validation as an EvaluationStrategy."""

    def __init__(
        self,
        validation_func: Callable[[Any], bool],
        feedback_message: str,
        strategies: list[FeedbackStrategy] | None = None,
        max_attempts: int = 3,
        on_exhausted: str = "return_last",
    ) -> None:
        self._validation_func = validation_func
        self._feedback_message = feedback_message
        self._strategies = strategies
        self._max_attempts = max_attempts
        self._on_exhausted = on_exhausted

    @property
    def name(self) -> str:
        return "validation"

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    @property
    def on_exhausted(self) -> str:
        return self._on_exhausted

    def evaluate(self, result: BatchResult) -> bool:
        """Return True if the result passes validation."""
        if not result.success:
            return False

        if (
            result.recovery_metadata
            and result.recovery_metadata.reprompt
            and result.recovery_metadata.reprompt.passed
        ):
            return True

        return safe_validate(
            self._validation_func,
            result.content,
            context=result.custom_id,
            catch=(Exception,),
        )

    def build_feedback(self, result: BatchResult) -> str:
        """Build validation feedback for a failing result."""
        if not result.success:
            return (
                "---\n"
                "The previous attempt failed due to an API error and produced no response.\n"
                "Please respond again."
            )
        return build_validation_feedback(
            failed_response=result.content,
            feedback_message=self._feedback_message,
            strategies=self._strategies,
        )
