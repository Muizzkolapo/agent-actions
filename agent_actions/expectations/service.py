"""Running an action's expectations around its generation call."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_actions.expectations.loader import SuiteLoadError, build_inline_suite, load_named_suite
from agent_actions.expectations.repair import compose_repair_prompt
from agent_actions.expectations.runner import JudgeDispatch, run_suite
from agent_actions.expectations.types import Expectation, Outcome, Suite, SuiteResult
from agent_actions.utils.constants import SCHEMA_KEY

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
    # One verdict per record the response carries. A response is usually a
    # single record, but an action whose LLM returns a JSON array produces one
    # record per element and each is validated on its own.
    suite_results: list[SuiteResult] | None = None


def _records_of(response: Any) -> list[dict[str, Any]] | None:
    """The record(s) a response carries, or None if it is not record-shaped.

    A single-record call arrives as a bare dict or a length-1 list; an action
    whose LLM returns a JSON array carries one record per element.
    """
    if isinstance(response, dict):
        return [response]
    if isinstance(response, list) and response and all(isinstance(r, dict) for r in response):
        return list(response)
    return None


def _combine(results: list[SuiteResult], suite_name: str) -> SuiteResult:
    """One verdict for the whole response: it passes only if every record does.

    With several records the same authored id appears once per record, so each
    outcome is tagged with its record index — otherwise a rule that failed on
    one record and passed on another is reported as both, and the repair prompt
    asks the model to fix and preserve the same thing.
    """
    if len(results) == 1:
        return results[0]
    outcomes = [
        outcome.model_copy(update={"id": f"{outcome.id}[{index}]"})
        for index, result in enumerate(results)
        for outcome in result.outcomes
    ]
    return SuiteResult(suite_name=suite_name, outcomes=outcomes)


class ExpectationsExhaustedError(Exception):
    """The repair loop ended without a pass and ``on_exhausted`` is ``raise``."""

    def __init__(self, action_name: str, failed_ids: list[str], iterations: int) -> None:
        self.action_name = action_name
        self.failed_ids = failed_ids
        self.iterations = iterations
        super().__init__(
            f"Action '{action_name}' exhausted {iterations} expectation iteration(s); "
            f"still failing: {', '.join(failed_ids) or '(none)'}"
        )


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
        schema: dict[str, Any] | None = None,
        on_exhausted: str = "return_last",
    ) -> None:
        if max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1, got: {max_iterations}")
        if repair not in ("none", "retry", "auto"):
            raise ValueError(
                f"repair must be 'none', 'retry', or 'auto'; got: {repair!r}. "
                "The prompt-mapping form is not supported yet."
            )
        if on_exhausted not in ("return_last", "fail", "raise"):
            raise ValueError(
                f"on_exhausted must be 'return_last', 'fail', or 'raise'; got: {on_exhausted!r}"
            )
        self.suite = suite
        self._on_exhausted = on_exhausted
        self.repair = repair
        self._judge = judge
        self._max_iterations = max_iterations
        self._schema = schema if isinstance(schema, dict) else None
        self._schema_digest: str | None = None
        self._hints = {e.resolved_id: e.hint for e in suite.expectations if e.hint}

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
        last_response: Any = None
        last_suite_result: SuiteResult | None = None
        last_suite_results: list[SuiteResult] | None = None

        for iteration in range(1, iterations + 1):
            response, executed = llm_operation(
                self._prompt_for(iteration, original_prompt, last_response, last_suite_result)
            )

            # A real record-granularity online call arrives as a length-1 list, not a
            # bare dict; a longer list (file granularity) has no expect: semantics.
            if isinstance(response, list) and len(response) == 1 and isinstance(response[0], dict):
                response = response[0]

            if not executed:
                if last_suite_result is not None:
                    # A regeneration that collapsed (inner recovery exhausted)
                    # must not downgrade a record that already had a verdict.
                    return self._exhausted_result(
                        last_response, last_suite_result, iteration, last_suite_results
                    )
                return ExpectationRunResult(response=response, executed=executed)

            records = _records_of(response)

            if self.repair == "none":
                if records is None:
                    return ExpectationRunResult(response=response, executed=executed)
                suite_results = self._validate_records(records, llm_context)
            else:
                structural = self._structural_results(response, records)
                suite_results = (
                    structural
                    if structural is not None
                    else self._validate_records(records or [], llm_context)
                )
            suite_result = _combine(suite_results, self.suite.name)
            if suite_result.overall_pass:
                return ExpectationRunResult(
                    response=response,
                    executed=True,
                    suite_result=suite_result,
                    iterations=iteration,
                    suite_results=suite_results,
                )
            last_response, last_suite_result = response, suite_result
            last_suite_results = suite_results

            # A rule that was skipped was never evaluated, so regenerating cannot
            # change its outcome — and the repair composer leaves it out of both
            # lists, naming nothing to fix. Stop generating, but still leave
            # through the exhaustion door: the record failed, and on_exhausted is
            # the author's decision about that whatever the rule's outcome was.
            if self.repair != "none" and all(o.skipped for o in suite_result.failed):
                logger.info(
                    "[%s] Expectations failed on rules that were never evaluated, "
                    "so there is nothing to regenerate: %s",
                    context or "expectations",
                    ", ".join(o.id for o in suite_result.failed),
                )
                iterations = iteration
                break

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

        if self.repair == "none":
            return ExpectationRunResult(
                response=response,
                executed=True,
                suite_result=suite_result,
                iterations=iterations,
                suite_results=suite_results,
            )
        return self._exhausted_result(response, suite_result, iterations, suite_results)

    def _validate_records(
        self, records: list[dict[str, Any]], llm_context: dict[str, Any] | None
    ) -> list[SuiteResult]:
        return [
            run_suite(self.suite, record, judge=self._judge, context_source=llm_context)
            for record in records
        ]

    def validate(
        self, response: Any, llm_context: dict[str, Any] | None = None
    ) -> SuiteResult | None:
        """Run the suite over an already-produced record, or None if it is not one.

        The batch path has its response before this service is reached, so it
        validates through here rather than through ``execute``. Sharing the
        service keeps the judge cache and budget identical on both paths.
        """
        if not isinstance(response, dict):
            return None
        return run_suite(self.suite, response, judge=self._judge, context_source=llm_context)

    def _exhausted_result(
        self,
        response: Any,
        suite_result: SuiteResult | None,
        iterations: int,
        suite_results: list[SuiteResult] | None = None,
    ) -> ExpectationRunResult:
        """Apply the on_exhausted policy to a loop that ended without a pass."""
        if self._on_exhausted == "raise":
            failed = (
                [o.id for o in suite_result.failed if o.severity == "error"] if suite_result else []
            )
            raise ExpectationsExhaustedError(self.suite.name, failed, iterations)
        if self._on_exhausted == "fail":
            return ExpectationRunResult(
                response=None,
                executed=False,
                suite_result=suite_result,
                iterations=iterations,
                exhausted=True,
                suite_results=suite_results,
            )
        return ExpectationRunResult(
            response=response,
            executed=True,
            suite_result=suite_result,
            iterations=iterations,
            exhausted=True,
            suite_results=suite_results,
        )

    def _prompt_for(
        self,
        iteration: int,
        original_prompt: str,
        last_response: Any,
        last_suite_result: SuiteResult | None,
    ) -> str:
        """The prompt for one generation; retry re-samples the original, auto composes feedback."""
        if self.repair == "auto" and iteration > 1 and last_suite_result is not None:
            return compose_repair_prompt(
                original_prompt, last_response, last_suite_result, self._hints
            )
        return original_prompt

    def _structural_results(
        self, response: Any, records: list[dict[str, Any]] | None
    ) -> list[SuiteResult] | None:
        """One verdict per record when any is not schema-conforming, else None.

        Each record carries its own outcome so a conforming record is never
        annotated with another record's failure.
        """
        if records is None:
            single = self._structural_result(response, None)
            return [single] if single is not None else None
        per_record = [self._structural_result(record, [record]) for record in records]
        if all(result is None for result in per_record):
            return None
        return [
            result if result is not None else SuiteResult(suite_name=self.suite.name, outcomes=[])
            for result in per_record
        ]

    def _structural_result(
        self, response: Any, records: list[dict[str, Any]] | None = None
    ) -> SuiteResult | None:
        """A failing verdict when the response is not a schema-conforming record, else None."""
        if records is None:
            detail = f"response was {type(response).__name__}, expected a JSON object"
            if self._schema:
                try:
                    from agent_actions.processing.recovery.reprompt import _extract_field_names

                    fields = _extract_field_names(self._schema)
                except Exception:
                    # A schema the extractor cannot walk degrades to feedback
                    # without field names; it must never crash the record.
                    logger.debug(
                        "Could not extract field names from the schema for '%s'",
                        self.suite.name,
                        exc_info=True,
                    )
                    fields = []
                if fields:
                    detail += " with the fields: " + ", ".join(str(f) for f in fields)
            return self._failing_structural(detail)
        if self._schema:
            from agent_actions.processing.recovery.response_validator import SchemaValidator

            for record in records:
                # The validator keeps per-call feedback state and records validate
                # concurrently, so it is constructed per call, never held on self.
                validator = SchemaValidator(self._schema, self.suite.name)
                if not validator.validate(record):
                    return self._failing_structural(validator.feedback_message)
        return None

    def _failing_structural(self, detail: str) -> SuiteResult:
        if self._schema_digest is None:
            # Lazy: observe-mode services never digest, and an idempotent
            # concurrent double-compute is harmless.
            self._schema_digest = self._digest_schema()
        outcome = Outcome(
            id="_structural",
            type="schema",
            severity="error",
            passed=False,
            detail=detail,
            definition_hash=self._schema_digest,
        )
        return SuiteResult(suite_name=self.suite.name, outcomes=[outcome])

    def _digest_schema(self) -> str:
        try:
            canonical = json.dumps(
                self._schema or {}, sort_keys=True, separators=(",", ":"), default=str
            )
        except (TypeError, ValueError):
            logger.debug(
                "Schema for '%s' is not JSON-canonicalizable; digesting its repr",
                self.suite.name,
            )
            canonical = repr(self._schema)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


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
    if isinstance(repair, dict):
        raise ConfigurationError(
            f"Action '{action_name}' uses the repair prompt-mapping form; custom "
            "repair prompts are not implemented yet. Use repair: retry or auto.",
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

    return ExpectationService(
        suite,
        repair=repair,
        judge=judge_dispatch,
        max_iterations=expect_config.get("max_iterations", 3),
        schema=(agent_config or {}).get(SCHEMA_KEY),
        on_exhausted=expect_config.get("on_exhausted", "return_last"),
    )
