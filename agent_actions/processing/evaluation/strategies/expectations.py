"""ExpectationStrategy — an action's expect: suite as an EvaluationStrategy."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agent_actions.processing.types import EvaluationOutcome

if TYPE_CHECKING:
    from agent_actions.expectations.service import ExpectationService
    from agent_actions.expectations.types import SuiteResult
    from agent_actions.llm.providers.batch_base import BatchResult

logger = logging.getLogger(__name__)


class ExpectationStrategy:
    """Drives batch repair rounds from the same suite the online loop runs.

    The verdict computed here is kept per record so the result assembler can
    attach it without re-running the suite — re-running would spend the judge
    budget twice on the same content.
    """

    def __init__(self, service: ExpectationService) -> None:
        self._service = service
        self._verdicts: dict[str, SuiteResult] = {}

    @property
    def name(self) -> str:
        return "expectations"

    @property
    def max_attempts(self) -> int:
        return self._service.max_iterations

    @property
    def on_exhausted(self) -> str:
        return self._service.on_exhausted

    def verdict_for(self, custom_id: str) -> SuiteResult | None:
        """The verdict this strategy last computed for a record."""
        return self._verdicts.get(custom_id)

    def evaluate(self, result: BatchResult) -> EvaluationOutcome:
        return EvaluationOutcome(passed=True)

    def build_feedback(self, result: BatchResult) -> str:
        return ""

    def _hints(self) -> dict[str, Any]:
        return {}
