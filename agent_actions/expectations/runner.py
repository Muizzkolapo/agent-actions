"""Running a suite of expectations over one record."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agent_actions.expectations import registry
from agent_actions.expectations.expression import evaluate_condition
from agent_actions.expectations.fields import FieldResolutionError, resolve, resolve_context
from agent_actions.expectations.types import Expectation, Outcome, Suite, SuiteResult

logger = logging.getLogger(__name__)

JudgeDispatch = Callable[[Expectation, Any, dict[str, Any] | None], tuple[bool, str, bool]]


class UnknownExpectationTypeError(Exception):
    """Raised when a suite names a type that is not registered."""


def run_suite(
    suite: Suite,
    record: dict[str, Any],
    *,
    judge: JudgeDispatch | None = None,
    context_source: dict[str, Any] | None = None,
) -> SuiteResult:
    """Evaluate every expectation in *suite* against *record*.

    Every expectation runs even after an earlier one fails: the repair composer
    needs the complete picture, both what broke and what must be preserved.
    """
    outcomes = [
        _run_one(expectation, record, judge=judge, context_source=context_source)
        for expectation in suite.expectations
    ]
    return SuiteResult(suite_name=suite.name, outcomes=outcomes)


def _run_one(
    expectation: Expectation,
    record: dict[str, Any],
    *,
    judge: JudgeDispatch | None,
    context_source: dict[str, Any] | None,
) -> Outcome:
    etype = registry.get(expectation.type)
    if etype is None:
        raise UnknownExpectationTypeError(
            f"Expectation '{expectation.resolved_id}' uses unregistered type "
            f"'{expectation.type}'. Known types: {', '.join(registry.known_types())}"
        )

    def outcome(passed: bool, detail: str, skipped: bool = False) -> Outcome:
        return Outcome(
            id=expectation.resolved_id,
            type=expectation.type,
            severity=expectation.severity,
            passed=passed,
            detail=detail,
            definition_hash=expectation.definition_hash(),
            skipped=skipped,
        )

    if expectation.type == "expression":
        passed, detail = evaluate_condition(str(expectation.params()["condition"]), record)
        return outcome(passed, detail)

    if expectation.field is None:
        raise ValueError(
            f"Expectation '{expectation.resolved_id}' has no field selector and "
            f"type '{expectation.type}' has no record-scoped dispatch in this runner"
        )

    try:
        inputs = resolve(record, expectation.field)
    except FieldResolutionError as exc:
        return outcome(False, str(exc))

    params = expectation.params

    if expectation.type == "llm_judge":
        if judge is None:
            raise ValueError(
                f"Expectation '{expectation.resolved_id}' is type llm_judge but no judge "
                "dispatcher was provided to run_suite()"
            )
        context: dict[str, Any] | None = None
        context_refs = params.get("context")
        if context_refs:
            if context_source is None:
                return outcome(False, "context: refs declared but no context source was provided")
            try:
                context = resolve_context(context_source, context_refs)
            except FieldResolutionError as exc:
                return outcome(False, str(exc))

        results = [judge(expectation, value, context) for value in inputs]
        failing = [(detail, skipped) for passed, detail, skipped in results if not passed]
        if failing:
            skipped_any = any(skipped for _, skipped in failing)
            return outcome(False, "; ".join(detail for detail, _ in failing), skipped=skipped_any)
        return outcome(True, "; ".join(detail for _, detail, _ in results if detail))

    details = [
        detail for value in inputs for passed, detail in [etype.check(value, params)] if not passed
    ]
    if details:
        return outcome(False, "; ".join(details))
    return outcome(True, "")
