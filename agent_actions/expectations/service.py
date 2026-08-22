"""Running an action's expectations around its generation call."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_actions.expectations.loader import SuiteLoadError, build_inline_suite, load_named_suite
from agent_actions.expectations.runner import JudgeDispatch, run_suite
from agent_actions.expectations.types import Expectation, Suite, SuiteResult

logger = logging.getLogger(__name__)

VERDICT_KEY = "expect"


@dataclass
class ExpectationRunResult:
    """What one expectation-guarded generation produced."""

    response: Any
    executed: bool
    suite_result: SuiteResult | None = None
    iterations: int = 0
    exhausted: bool = False


class ExpectationService:
    """Wraps LLM execution with expectation validation.

    ``execute`` takes the same ``llm_operation`` contract as ``RepromptService``,
    so this composes as the outermost recovery layer.
    """

    def __init__(
        self,
        suite: Suite,
        repair: str | dict[str, Any],
        *,
        judge: JudgeDispatch | None = None,
        max_iterations: int = 3,
    ) -> None:
        if max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1, got: {max_iterations}")
        self.suite = suite
        self.repair = repair
        self._judge = judge
        self._max_iterations = max_iterations

    def execute(
        self,
        llm_operation: Callable[[str], tuple[Any, bool]],
        original_prompt: str,
        context: str = "",
        llm_context: dict[str, Any] | None = None,
    ) -> ExpectationRunResult:
        """Generate, validate, and — under a repair policy — regenerate until the suite passes."""
        iterations = self._max_iterations if self.repair != "none" else 1
        suite_result: SuiteResult | None = None
        response: Any = None
        executed = False
        last_response: dict[str, Any] | None = None
        last_suite_result: SuiteResult | None = None

        for iteration in range(1, iterations + 1):
            response, executed = llm_operation(self._prompt_for(iteration, original_prompt))

            # A real record-granularity online call arrives as a length-1 list, not a
            # bare dict; a longer list (file granularity) has no expect: semantics.
            if isinstance(response, list) and len(response) == 1 and isinstance(response[0], dict):
                response = response[0]

            if not executed or not isinstance(response, dict):
                if last_response is not None and last_suite_result is not None:
                    # A regeneration that collapsed (inner recovery exhausted)
                    # must not downgrade a record that already had data.
                    return ExpectationRunResult(
                        response=last_response,
                        executed=True,
                        suite_result=last_suite_result,
                        iterations=iteration,
                        exhausted=True,
                    )
                return ExpectationRunResult(response=response, executed=executed)

            suite_result = run_suite(
                self.suite, response, judge=self._judge, context_source=llm_context
            )
            if suite_result.overall_pass:
                return ExpectationRunResult(
                    response=response,
                    executed=True,
                    suite_result=suite_result,
                    iterations=iteration,
                )
            last_response, last_suite_result = response, suite_result
            if self.repair == "none":
                logger.info(
                    "[%s] Expectations failed: %s",
                    context or "expectations",
                    ", ".join(o.id for o in suite_result.failed),
                )
            else:
                logger.info(
                    "[%s] Expectations failed (iteration %d/%d): %s",
                    context or "expectations",
                    iteration,
                    iterations,
                    ", ".join(o.id for o in suite_result.failed),
                )

        return ExpectationRunResult(
            response=response,
            executed=True,
            suite_result=suite_result,
            iterations=iterations,
            exhausted=self.repair != "none",
        )

    def _prompt_for(self, iteration: int, original_prompt: str) -> str:
        """The prompt for one generation; retry always re-samples the original."""
        return original_prompt


def attach_verdict(response: dict[str, Any], suite_result: SuiteResult) -> dict[str, Any]:
    """Return *response* with the verdict under the ``expect`` key."""
    return {**response, VERDICT_KEY: suite_result.to_record_dict()}


def create_expectation_service_from_config(
    expect_config: dict[str, Any] | None,
    *,
    action_name: str,
    schema_name: str | None = None,
    agent_config: dict[str, Any] | None = None,
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

    judge_dispatch: JudgeDispatch | None = None
    if any(expectation.type == "llm_judge" for expectation in suite.expectations):
        from agent_actions.expectations.judge import CachedJudge, JudgeBudget

        cached_judge = CachedJudge(agent_config or {}, action_name=action_name)
        budget = JudgeBudget(expect_config.get("judge_budget"))

        def judge_dispatch(
            expectation: Expectation, value: Any, context: dict[str, Any] | None
        ) -> tuple[bool, str, bool]:
            cached = cached_judge.lookup(expectation, value)
            if cached is not None:
                return (*cached, False)
            if not budget.try_acquire():
                return False, f"judge budget exhausted ({budget.remaining} calls remaining)", True
            try:
                passed, detail = cached_judge.call_and_cache(expectation, value, context=context)
            except Exception as exc:
                logger.warning(
                    "[%s] Judge call failed for '%s', treating as a failed outcome",
                    action_name,
                    expectation.resolved_id,
                    exc_info=True,
                )
                return False, f"judge call failed: {exc}", False
            return passed, detail, False

    return ExpectationService(suite, repair=repair, judge=judge_dispatch)
