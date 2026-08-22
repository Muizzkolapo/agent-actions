"""Running a suite of expectations over one record."""

from __future__ import annotations

import logging
from typing import Any

from agent_actions.expectations import registry
from agent_actions.expectations.fields import FieldResolutionError, resolve
from agent_actions.expectations.types import Expectation, Outcome, Suite, SuiteResult

logger = logging.getLogger(__name__)


class UnknownExpectationTypeError(Exception):
    """Raised when a suite names a type that is not registered."""


def run_suite(suite: Suite, record: dict[str, Any]) -> SuiteResult:
    """Evaluate every expectation in *suite* against *record*.

    Every expectation runs even after an earlier one fails: the repair composer
    needs the complete picture, both what broke and what must be preserved.
    """
    outcomes = [_run_one(expectation, record) for expectation in suite.expectations]
    return SuiteResult(suite_name=suite.name, outcomes=outcomes)


def _run_one(expectation: Expectation, record: dict[str, Any]) -> Outcome:
    etype = registry.get(expectation.type)
    if etype is None:
        raise UnknownExpectationTypeError(
            f"Expectation '{expectation.resolved_id}' uses unregistered type "
            f"'{expectation.type}'. Known types: {', '.join(registry.known_types())}"
        )

    def outcome(passed: bool, detail: str) -> Outcome:
        return Outcome(
            id=expectation.resolved_id,
            type=expectation.type,
            severity=expectation.severity,
            passed=passed,
            detail=detail,
            definition_hash=expectation.definition_hash(),
        )

    try:
        inputs = resolve(record, expectation.field)
    except FieldResolutionError as exc:
        return outcome(False, str(exc))

    params = expectation.params()
    details = [
        detail for value in inputs for passed, detail in [etype.check(value, params)] if not passed
    ]
    if details:
        return outcome(False, "; ".join(details))
    return outcome(True, "")
