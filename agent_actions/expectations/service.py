"""Running an action's expectations around its generation call."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigurationError
from agent_actions.expectations.loader import (
    NoRulesDeclared,
    SuiteLoadError,
    build_inline_suite,
    build_suite_from_schema_data,
    load_named_suite,
)
from agent_actions.expectations.repair import (
    check_repair_template,
    compose_repair_prompt,
    render_repair_template,
)
from agent_actions.expectations.runner import JudgeDispatch, run_suite
from agent_actions.expectations.types import Expectation, Outcome, Suite, SuiteResult
from agent_actions.utils.constants import SCHEMA_KEY, SCHEMA_NAME_KEY, VERDICT_KEY

logger = logging.getLogger(__name__)

# The type stamped on the structural gate's own outcome. No registered
# expectation type uses it, so it identifies a schema failure unambiguously.
STRUCTURAL_OUTCOME_TYPE = "schema"


def _check_repair_mode(key: str, mode: Any, *, allow_none: bool) -> None:
    """Both regeneration keys take the same vocabulary; this is the one check.

    ``none`` turns the loop off entirely, so it belongs to ``repair:`` alone —
    there is no such thing as not regenerating one kind of failure.
    """
    allowed = ("none", "retry", "auto") if allow_none else ("retry", "auto")
    if isinstance(mode, dict):
        if set(mode) != {"prompt"}:
            raise ValueError(
                f"{key}: mapping form takes exactly one key, 'prompt'; got: {sorted(mode)}"
            )
        check_repair_template(mode["prompt"])
        return
    if mode not in allowed:
        raise ValueError(
            f"{key} must be one of {', '.join(allowed)} or a {{prompt: ...}} mapping; got: {mode!r}"
        )


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
    if isinstance(response, list) and any(isinstance(r, dict) for r in response):
        return list(response)
    return None


def _combine(results: list[SuiteResult], suite_name: str) -> SuiteResult:
    """One verdict for the whole response: it passes only if every record does.

    With several records the same authored id appears once per record, so each
    outcome is tagged with its record index — otherwise a rule that failed on
    one record and passed on another is reported as both, and the repair prompt
    asks the model to fix and preserve the same thing.
    """
    if not results:
        raise ValueError("a response with no records has nothing to combine")
    if len(results) == 1:
        return results[0]
    outcomes = [
        outcome.model_copy(update={"id": f"{outcome.id}[{index}]"})
        for index, result in enumerate(results)
        for outcome in result.outcomes
    ]
    return SuiteResult(suite_name=suite_name, outcomes=outcomes)


class ExpectationsExhaustedError(RuntimeError):
    """The repair loop ended without a pass and ``on_exhausted`` is ``raise``.

    A RuntimeError so it halts the run: the batch result loop re-raises those
    and logs-and-continues past anything else, and ``raise`` is the policy that
    is supposed to stop everything.
    """

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
        structural: str | dict[str, Any] = "retry",
    ) -> None:
        if max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1, got: {max_iterations}")
        _check_repair_mode("repair", repair, allow_none=True)
        if on_exhausted not in ("return_last", "fail", "raise"):
            raise ValueError(
                f"on_exhausted must be 'return_last', 'fail', or 'raise'; got: {on_exhausted!r}"
            )
        _check_repair_mode("structural", structural, allow_none=False)
        if repair == "none" and structural != "retry":
            raise ValueError(
                "structural: decides how a schema failure is regenerated, so it has no "
                "meaning under repair: none, which never regenerates"
            )
        self.suite = suite
        self._on_exhausted = on_exhausted
        self.repair = repair
        self.structural = structural
        self._judge = judge
        self._max_iterations = max_iterations
        self._schema = schema if isinstance(schema, dict) else None
        self._schema_digest: str | None = None
        self._hints = {e.resolved_id: e.hint for e in suite.expectations if e.hint}
        # Set by the factory when the suite judges; the deferred batch path
        # reads what is left so the budget bounds the run, not one round.
        self._judge_budget: Any = None

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

            suite_result, suite_results = self.verdict_for_response(
                response, llm_context, check_schema=self.repair != "none"
            )
            if suite_result is None:
                return ExpectationRunResult(response=response, executed=executed)
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

    @property
    def judge_budget_remaining(self) -> int | None:
        """Judge calls still available, or None when the budget is uncapped.

        A deferred batch rebuilds this service on every pass, so the caller
        persists this between rounds to keep the budget bounding the run rather
        than each round.
        """
        return self._judge_budget.remaining if self._judge_budget is not None else None

    @property
    def max_iterations(self) -> int:
        """Total generations per record under a repair policy, counting the first."""
        return self._max_iterations

    @property
    def on_exhausted(self) -> str:
        return self._on_exhausted

    @property
    def hints(self) -> dict[str, str]:
        """Each rule's author-supplied remedy text, keyed by resolved id."""
        return self._hints

    def verdict_for_response(
        self,
        response: Any,
        llm_context: dict[str, Any] | None = None,
        *,
        check_schema: bool,
    ) -> tuple[SuiteResult | None, list[SuiteResult]]:
        """One verdict for a whole response, plus the per-record verdicts behind it.

        A response carries one record or many; each is judged on its own so a
        malformed sibling neither fails a conforming record nor buys it a pass.
        Returns ``(None, [])`` when the response is not record-shaped and the
        caller does not want the structural gate — observe mode has nothing to
        say about a response it cannot read.
        """
        records = _records_of(response)
        if records is None:
            if not check_schema:
                return None, []
            suite_results = [self._non_record_verdict(response)]
        else:
            suite_results = [
                self._record_verdict(record, llm_context, check_schema=check_schema)
                for record in records
            ]
        return _combine(suite_results, self.suite.name), suite_results

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
        suite_results: list[SuiteResult] | None,
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
        if iteration == 1 or last_suite_result is None:
            return original_prompt
        mode = self._mode_for(last_suite_result)
        if isinstance(mode, dict):
            return render_repair_template(
                mode["prompt"], original_prompt, last_response, last_suite_result, self._hints
            )
        if mode != "auto":
            return original_prompt
        return compose_repair_prompt(original_prompt, last_response, last_suite_result, self._hints)

    def _mode_for(self, suite_result: SuiteResult) -> str | dict[str, Any]:
        """Which regeneration mode governs the failure that just happened.

        A schema failure and a rule failure carry different information: the
        rule names a defect in usable output, the schema failure means there was
        no usable output to preserve. Matching on the outcome's type rather than
        its id because a multi-record verdict suffixes ids with their index.
        """
        failed = suite_result.failed
        if failed and all(outcome.type == STRUCTURAL_OUTCOME_TYPE for outcome in failed):
            return self.structural
        return self.repair

    def _record_verdict(
        self, record: Any, llm_context: dict[str, Any] | None, *, check_schema: bool
    ) -> SuiteResult:
        """One record's verdict: structural failure if malformed, else its own rules.

        Observe mode marks a malformed element but never applies the schema
        gate, which belongs to the repair loop.
        """
        if not isinstance(record, dict):
            return self._non_record_verdict(record)
        if check_schema:
            schema_failure = self._schema_verdict(record)
            if schema_failure is not None:
                return schema_failure
        return run_suite(self.suite, record, judge=self._judge, context_source=llm_context)

    def _non_record_verdict(self, response: Any) -> SuiteResult:
        """The verdict for a response that carries no records at all."""
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

    def _schema_verdict(self, record: dict[str, Any]) -> SuiteResult | None:
        """A failing verdict when *record* does not conform to the schema, else None."""
        if not self._schema:
            return None
        from agent_actions.processing.recovery.response_validator import SchemaValidator

        # The validator keeps per-call feedback state and records validate
        # concurrently, so it is constructed per call, never held on self.
        validator = SchemaValidator(self._schema, self.suite.name)
        if validator.validate(record):
            return None
        return self._failing_structural(validator.feedback_message)

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


def attach_verdicts(response: Any, suite_results: list[SuiteResult]) -> Any:
    """Return *response* with each record carrying its own verdict.

    Pairs one verdict per record in order, which is the order
    `verdict_for_response` produced them in. A response whose record count no
    longer matches its verdicts is returned untouched rather than mis-paired.
    """
    records = _records_of(response)
    if records is None or len(records) != len(suite_results):
        return response
    annotated = [
        attach_verdict(record, verdict) if isinstance(record, dict) else record
        for record, verdict in zip(records, suite_results, strict=True)
    ]
    return annotated[0] if isinstance(response, dict) else annotated


class ExpectationConfigurationError(ConfigurationError):
    """An `expect:` block that cannot be resolved for the action at all.

    Distinct from a per-record configuration problem: this one fails identically
    for every input file, so a batch run must stop rather than log it per file
    and finish reporting success with each of them missing from the output.
    """


def create_expectation_service_from_config(
    expect_config: dict[str, Any] | None,
    *,
    action_name: str,
    agent_config: dict[str, Any] | None = None,
    project_root: Path | None = None,
    judge_budget_remaining: int | None = None,
) -> ExpectationService | None:
    """Build a service from an action's ``expect:`` block, or None if absent.

    ``judge_budget_remaining`` replaces the configured budget for this
    construction. A deferred batch rebuilds the service each pass, so the caller
    carries the balance rather than letting every round start from full.
    """
    if expect_config is None:
        return None

    repair = expect_config.get("repair", "auto")

    suite_name = expect_config.get("suite")
    entries = expect_config.get("expectations")
    config = agent_config or {}
    schema_data: dict[str, Any] | None = None
    if suite_name is None and entries is None:
        # A bare block reads the expectations: block of the action's own
        # schema. A named schema is inlined into the config at load time and
        # its name dropped, so the resolved dict is the authority; the name
        # survives only when loading could not inline it.
        schema_name = config.get(SCHEMA_NAME_KEY) or None
        raw_schema = config.get(SCHEMA_KEY)
        if isinstance(raw_schema, dict):
            schema_data = raw_schema
        elif schema_name:
            suite_name = schema_name
        else:
            raise ExpectationConfigurationError(
                f"Action '{action_name}' has a bare expect: block but no schema "
                "to read expectations from. Add a schema:, or use suite: or an "
                "inline expectations: list.",
                context={"action": action_name},
            )
    if schema_data is not None:
        try:
            suite = build_suite_from_schema_data(
                schema_name or f"{action_name}:schema", schema_data
            )
        except NoRulesDeclared as exc:
            if repair == "none":
                raise ExpectationConfigurationError(
                    f"Action '{action_name}' has a bare expect: block under "
                    f"repair: none, but its schema has no expectations to run, so "
                    f"nothing would be checked and nothing regenerated: {exc}",
                    context={"action": action_name},
                ) from exc
            # Under a repair policy the block is the structural contract on its
            # own: conform to the schema, regenerate when the output does not.
            # The suite is empty and the gate is what enforces.
            suite = Suite(name=schema_name or f"{action_name}:schema", expectations=[])
        except ValueError as exc:
            # The schema has rules; they are in the wrong place or the wrong
            # shape, which is a different thing from having none.
            raise ExpectationConfigurationError(
                f"Action '{action_name}': {exc}",
                context={"action": action_name},
            ) from exc
    elif suite_name:
        # The action config carries the project root, stamped when the workflow
        # was loaded. Preflight passes it explicitly and keeps precedence; every
        # runtime caller has only the config, so reading it here resolves the
        # suite for all of them.
        if project_root is None:
            project_root = Path(config["_project_root"]) if config.get("_project_root") else None
        if project_root is None:
            raise ExpectationConfigurationError(
                f"Action '{action_name}' resolves suite '{suite_name}' but no "
                "project root was available to resolve it.",
                context={"action": action_name, "suite": suite_name},
            )
        try:
            suite = load_named_suite(suite_name, Path(project_root))
        except SuiteLoadError as exc:
            raise ExpectationConfigurationError(
                f"Action '{action_name}': {exc}",
                context={"action": action_name, "suite": suite_name},
            ) from exc
    else:
        suite = build_inline_suite(entries or [], action_name)

    judge_dispatch: JudgeDispatch | None = None
    if any(expectation.type == "llm_judge" for expectation in suite.expectations):
        from agent_actions.expectations.judge import CachedJudge, JudgeBudget

        cached_judge = CachedJudge(config, action_name=action_name)
        # judge_budget bounds the whole run, not one construction of the
        # service. A deferred batch rebuilds the service on each pass, so the
        # caller carries what is left and hands it back here.
        budget = JudgeBudget(
            judge_budget_remaining
            if judge_budget_remaining is not None
            else expect_config.get("judge_budget")
        )

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

    service = ExpectationService(
        suite,
        repair=repair,
        judge=judge_dispatch,
        max_iterations=expect_config.get("max_iterations", 3),
        schema=config.get(SCHEMA_KEY),
        on_exhausted=expect_config.get("on_exhausted", "return_last"),
        structural=expect_config.get("structural", "retry"),
    )
    service._judge_budget = budget if judge_dispatch is not None else None
    return service
