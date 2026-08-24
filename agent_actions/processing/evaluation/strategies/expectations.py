"""ExpectationStrategy — an action's expect: suite as an EvaluationStrategy."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agent_actions.processing.types import EvaluationOutcome

if TYPE_CHECKING:
    from agent_actions.expectations.service import ExpectationService
    from agent_actions.expectations.types import SuiteResult
    from agent_actions.llm.providers.batch_base import BatchResult

logger = logging.getLogger(__name__)


def _verdict_key(result: BatchResult) -> str | None:
    """The record's identity, or None when it has none to key on.

    A provider stamps the same sentinel on every result that came back without a
    correlation id, so keying on it would make the last one's verdict overwrite
    every other's — and a record that passed would ship a failing verdict about
    data it does not have.
    """
    from agent_actions.llm.providers.batch_base import UNIDENTIFIED_RECORD

    key = result.custom_id
    return str(key) if key and key != UNIDENTIFIED_RECORD else None


class ExpectationStrategy:
    """Drives batch repair rounds from the same suite the online loop runs.

    Each verdict is kept against its record so the result assembler can attach
    it without re-running the suite; a second run would spend the judge budget
    again on content it has already judged.
    """

    def __init__(self, service: ExpectationService) -> None:
        self._service = service
        self._verdicts: dict[str, SuiteResult] = {}
        self._record_verdicts: dict[str, list[SuiteResult]] = {}

    @property
    def name(self) -> str:
        return "expectations"

    @property
    def max_attempts(self) -> int:
        return self._service.max_iterations

    @property
    def on_exhausted(self) -> str:
        return self._service.on_exhausted

    @property
    def judge_budget_remaining(self) -> int | None:
        """Judge calls left, for the next deferred round to start from."""
        return self._service.judge_budget_remaining

    def verdict_for(self, custom_id: str) -> SuiteResult | None:
        """The verdict this strategy last computed for a record."""
        return self._verdicts.get(custom_id)

    def evaluate(self, result: BatchResult) -> EvaluationOutcome:
        if not result.success:
            return EvaluationOutcome(passed=False, failure_type="api_error", error=result.error)

        # check_schema mirrors the online repair loop: a response that is not
        # record-shaped, or a record the schema rejects, becomes a structural
        # failure the regeneration can act on rather than an unjudged pass.
        verdict, per_record = self._service.verdict_for_response(result.content, check_schema=True)
        if verdict is None:
            return EvaluationOutcome(passed=False, failure_type="expectation_fail")

        key = _verdict_key(result)
        if key is not None:
            self._verdicts[key] = verdict
            self._record_verdicts[key] = per_record
        elif per_record:
            # Nothing to key on, so the verdict goes on the record now rather
            # than through the map, where the next such record would overwrite
            # it. It cannot be repaired either — a record with no id has no
            # context_map row to rebuild its prompt from — so this is its
            # only chance to carry one.
            from agent_actions.expectations.service import attach_verdicts

            result.content = attach_verdicts(result.content, per_record)
        if verdict.overall_pass:
            return EvaluationOutcome(passed=True)
        return EvaluationOutcome(
            passed=False,
            failure_type="expectation_fail",
            error=", ".join(outcome.id for outcome in verdict.failed),
        )

    def build_feedback(self, result: BatchResult) -> str:
        """What to append to the prompt this record was already sent.

        ``repair: retry`` re-sends the original prompt untouched, so it has
        nothing to append.
        """
        if self._service.repair != "auto":
            return ""
        key = _verdict_key(result)
        verdict = self._verdicts.get(key) if key else None
        if verdict is None:
            logger.warning(
                "No expectation verdict for %s — re-sending the original prompt",
                result.custom_id,
            )
            return ""

        from agent_actions.expectations.repair import compose_repair_feedback

        return compose_repair_feedback(result.content, verdict, self._service.hints)

    def write_verdicts(self, results: list[BatchResult]) -> None:
        """Put each record's verdict on the record, as the online path does.

        The result assembler skips its own validation under a repair policy, so
        this is where the verdict enters the record — and it is the one this
        loop already computed, not a second run that would spend the judge
        budget again on the same content.
        """
        from agent_actions.expectations.service import attach_verdicts

        for result in results:
            key = _verdict_key(result)
            # A record with no identity had its verdict attached when it was
            # evaluated; there is nothing keyed here to look up.
            per_record = self._record_verdicts.get(key) if key else None
            if per_record:
                result.content = attach_verdicts(result.content, per_record)
