"""
EvaluationLoop — graduated pool pattern for batch result evaluation.

Strategy-agnostic: concrete strategies (validation, critique, etc.)
implement the EvaluationStrategy protocol and are plugged in by callers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agent_actions.processing.types import EvaluationMetadata, RecoveryMetadata

if TYPE_CHECKING:
    from agent_actions.llm.providers.batch_base import BatchResult

logger = logging.getLogger(__name__)


@runtime_checkable
class EvaluationStrategy(Protocol):
    """What changes between reprompt, critique, etc."""

    def evaluate(self, result: BatchResult) -> bool: ...

    def build_feedback(self, result: BatchResult) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def max_attempts(self) -> int: ...

    @property
    def on_exhausted(self) -> str: ...


class EvaluationLoop:
    """The mechanism. Same for all strategies."""

    def __init__(self, strategy: EvaluationStrategy) -> None:
        self.strategy = strategy

    def _is_already_graduated(self, result: BatchResult) -> bool:
        """Check if a result was already graduated in a prior cycle."""
        meta = getattr(result, "recovery_metadata", None)
        if meta is None:
            return False
        eval_meta = getattr(meta, "evaluation", None)
        if eval_meta is None:
            return False
        return getattr(eval_meta, "passed", False) is True

    def split(self, results: list[BatchResult]) -> tuple[list[BatchResult], list[BatchResult]]:
        """→ (graduated, still_failing). Skips already-graduated."""
        graduated: list[BatchResult] = []
        still_failing: list[BatchResult] = []

        for result in results:
            if self._is_already_graduated(result):
                graduated.append(result)
                continue

            if self.strategy.evaluate(result):
                graduated.append(result)
            else:
                still_failing.append(result)

        logger.info(
            "EvaluationLoop[%s].split: %d graduated, %d still failing (of %d total)",
            self.strategy.name,
            len(graduated),
            len(still_failing),
            len(results),
        )
        return graduated, still_failing

    def tag_graduated(self, results: list[BatchResult]) -> None:
        """Mark as done. Never evaluated again."""
        for result in results:
            meta = getattr(result, "recovery_metadata", None)
            if not isinstance(meta, RecoveryMetadata):
                meta = RecoveryMetadata()
            meta.evaluation = EvaluationMetadata(
                passed=True,
                strategy_name=self.strategy.name,
            )
            result.recovery_metadata = meta

    def build_resubmission(self, failed: list[BatchResult], context_map: dict) -> list[dict]:
        """Append strategy.build_feedback() to each, return submission records."""
        submissions: list[dict] = []

        for result in failed:
            custom_id = result.custom_id
            context = context_map.get(custom_id, {})
            feedback = self.strategy.build_feedback(result)

            submission = {
                "custom_id": custom_id,
                "context": context,
                "feedback": feedback,
                "user_content": context.get("user_content", "") + "\n\n" + feedback,
            }
            submissions.append(submission)

        logger.info(
            "EvaluationLoop[%s].build_resubmission: %d records",
            self.strategy.name,
            len(submissions),
        )
        return submissions
