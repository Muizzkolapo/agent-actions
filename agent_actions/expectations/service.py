"""Running an action's expectations around its generation call."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_actions.expectations.loader import SuiteLoadError, build_inline_suite, load_named_suite
from agent_actions.expectations.runner import run_suite
from agent_actions.expectations.types import Suite, SuiteResult

logger = logging.getLogger(__name__)

VERDICT_KEY = "expect"


@dataclass
class ExpectationRunResult:
    """What one expectation-guarded generation produced."""

    response: Any
    executed: bool
    suite_result: SuiteResult | None = None
    iterations: int = 0


class ExpectationService:
    """Wraps LLM execution with expectation validation.

    ``execute`` takes the same ``llm_operation`` contract as ``RepromptService``,
    so this composes as the outermost recovery layer.
    """

    def __init__(self, suite: Suite, repair: str | dict[str, Any]) -> None:
        self.suite = suite
        self.repair = repair

    def execute(
        self,
        llm_operation: Callable[[str], tuple[Any, bool]],
        original_prompt: str,
        context: str = "",
    ) -> ExpectationRunResult:
        """Generate once, then validate. Repair modes arrive with the loop."""
        response, executed = llm_operation(original_prompt)

        if not executed or not isinstance(response, dict):
            return ExpectationRunResult(response=response, executed=executed)

        suite_result = run_suite(self.suite, response)
        if not suite_result.overall_pass:
            logger.info(
                "[%s] Expectations failed: %s",
                context or "expectations",
                ", ".join(o.id for o in suite_result.failed),
            )
        return ExpectationRunResult(
            response=response, executed=True, suite_result=suite_result, iterations=1
        )


def attach_verdict(response: dict[str, Any], suite_result: SuiteResult) -> dict[str, Any]:
    """Return *response* with the verdict under the ``expect`` key."""
    return {**response, VERDICT_KEY: suite_result.to_record_dict()}


def create_expectation_service_from_config(
    expect_config: dict[str, Any] | None,
    *,
    action_name: str,
    schema_name: str | None = None,
    project_root: Path | None = None,
) -> ExpectationService | None:
    """Build a service from an action's ``expect:`` block, or None if absent."""
    from agent_actions.errors import ConfigurationError

    if expect_config is None:
        return None

    repair = expect_config.get("repair", "auto")
    if repair != "none":
        raise ConfigurationError(
            f"Action '{action_name}' sets repair: {repair!r}, but this build only "
            "implements observe mode. Use repair: none to validate and report "
            "without regenerating.",
            context={"action": action_name, "repair": repair},
        )

    suite_name = expect_config.get("suite")
    entries = expect_config.get("expectations")
    if suite_name is None and entries is None:
        # A bare block reads the expectations: block of the action's own schema file.
        if not schema_name:
            raise ConfigurationError(
                f"Action '{action_name}' has a bare expect: block but no named "
                "schema: file to read expectations from. Name one with suite: "
                "or declare expectations: inline.",
                context={"action": action_name},
            )
        suite_name = schema_name
    if suite_name:
        if project_root is None:
            raise ConfigurationError(
                f"Action '{action_name}' resolves suite '{suite_name}' but no "
                "project root was available to resolve it.",
                context={"action": action_name, "suite": suite_name},
            )
        try:
            suite = load_named_suite(suite_name, Path(project_root))
        except SuiteLoadError as exc:
            raise ConfigurationError(
                f"Action '{action_name}': {exc}",
                context={"action": action_name, "suite": suite_name},
            ) from exc
    else:
        suite = build_inline_suite(entries or [], action_name)

    return ExpectationService(suite, repair=repair)
