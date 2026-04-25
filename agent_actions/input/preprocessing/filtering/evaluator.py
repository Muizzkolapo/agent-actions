"""Unified guard evaluation for batch and online modes."""

import logging
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from agent_actions.errors.configuration import ConfigValidationError
from agent_actions.input.preprocessing.filtering.guard_filter import (
    ErrorCategory,
    FilterItemRequest,
    FilterResult,
    GuardFilter,
    get_global_guard_filter,
)
from agent_actions.utils.udf_management.tooling import execute_user_defined_function

_UNSUPPORTED_BEHAVIORS = frozenset({"write_to", "reprocess"})

logger = logging.getLogger(__name__)


class GuardBehavior(StrEnum):
    """Guard evaluation behavior when condition is not met."""

    SKIP = "skip"
    FILTER = "filter"
    WARN = "warn"


@dataclass
class GuardResult:
    """Result of guard evaluation."""

    should_execute: bool
    behavior: GuardBehavior | None = None
    error: str | None = None
    matched: bool = True

    @classmethod
    def passed(cls) -> "GuardResult":
        """Guard passed - item should be executed."""
        return cls(should_execute=True, matched=True)

    @classmethod
    def skipped(cls, error: str | None = None) -> "GuardResult":
        """Guard failed with skip behavior - use passthrough."""
        return cls(should_execute=False, behavior=GuardBehavior.SKIP, matched=False, error=error)

    @classmethod
    def filtered(cls, error: str | None = None) -> "GuardResult":
        """Guard failed with filter behavior - exclude entirely."""
        return cls(should_execute=False, behavior=GuardBehavior.FILTER, matched=False, error=error)

    @classmethod
    def warned(cls) -> "GuardResult":
        """Guard failed with warn behavior - proceed but flag for logging."""
        return cls(should_execute=True, behavior=GuardBehavior.WARN, matched=False)

    @classmethod
    def from_filter_result(
        cls, filter_result: FilterResult, behavior: GuardBehavior, passthrough_on_error: bool
    ) -> "GuardResult":
        """Create GuardResult from FilterResult."""
        if not filter_result.success:
            # Semantic errors bypass passthrough_on_error — the condition itself is broken.
            if filter_result.error_category == ErrorCategory.SEMANTIC:
                logger.warning(
                    "Guard: semantic error in condition, applying '%s' behavior: %s",
                    behavior,
                    filter_result.error,
                )
                if behavior == GuardBehavior.WARN:
                    return cls.warned()
                if behavior == GuardBehavior.SKIP:
                    return cls.skipped(error=filter_result.error)
                return cls.filtered(error=filter_result.error)

            # DATA/TIMEOUT errors respect passthrough_on_error (existing behavior)
            if passthrough_on_error:
                logger.warning(
                    "Guard: condition evaluation failed, proceeding (passthrough_on_error=True): %s",
                    filter_result.error,
                )
                return cls.passed()
            logger.warning(
                "Guard: condition evaluation failed, applying behavior '%s' (passthrough_on_error=False): %s",
                behavior,
                filter_result.error,
            )
            if behavior == GuardBehavior.WARN:
                return cls.warned()
            if behavior == GuardBehavior.SKIP:
                return cls.skipped(error=filter_result.error)
            return cls.filtered(error=filter_result.error)

        if not filter_result.matched:
            logger.debug("Guard: condition not matched, behavior='%s'", behavior)
            if behavior == GuardBehavior.WARN:
                return cls.warned()
            if behavior == GuardBehavior.SKIP:
                return cls.skipped()
            return cls.filtered()

        return cls.passed()


class GuardEvaluator:
    """Unified guard evaluation for batch and online modes."""

    def __init__(self, guard_filter: GuardFilter | None = None):
        """Initialize GuardEvaluator."""
        self._filter = guard_filter or get_global_guard_filter()

    def evaluate(
        self,
        item: Any,
        guard_config: dict[str, Any] | None,
        context: dict[str, Any] | None = None,
        conditional_clause: str | None = None,
    ) -> GuardResult:
        """Evaluate guard conditions, optionally with full context.

        When *context* is provided, item content is merged with context data
        (passthrough fields, source data) before evaluation.  When *context*
        is ``None``, evaluation uses the item directly.
        """
        if context is not None:
            eval_data = self._build_evaluation_context(item, context)
        else:
            eval_data = item

        if conditional_clause:
            result = self._evaluate_conditional_clause(eval_data, conditional_clause)
            if result is not None:
                return result

        return self._evaluate_guard(eval_data, guard_config)

    def _evaluate_conditional_clause(
        self, context: Any, conditional_clause: str
    ) -> GuardResult | None:
        """Evaluate legacy UDF conditional clause; returns None if passed, GuardResult.skipped() if failed."""
        clause = (conditional_clause or "").lower()
        if not clause:
            return None

        try:
            if not execute_user_defined_function(clause, context):
                logger.debug("Guard: conditional_clause '%s' evaluated to False, skipping", clause)
                return GuardResult.skipped()
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            logger.warning("Guard: conditional_clause evaluation failed: %s, proceeding", e)
            # Don't skip on UDF errors - proceed with execution

        return None

    def _evaluate_guard(self, context: Any, guard_config: dict[str, Any] | None) -> GuardResult:
        """Evaluate guard condition against context data."""
        if not guard_config:
            return GuardResult.passed()

        scope = guard_config.get("scope", "item")
        if scope != "item":
            return GuardResult.passed()

        clause = guard_config.get("clause")
        if not clause:
            return GuardResult.passed()

        behavior_str = guard_config.get("behavior", "filter")
        if behavior_str in _UNSUPPORTED_BEHAVIORS:
            raise ConfigValidationError(
                "behavior",
                f"Guard behavior '{behavior_str}' is not supported in guard evaluation. "
                f"Only 'skip', 'filter', and 'warn' are valid on_false values for guards.",
                context={"behavior": behavior_str},
            )
        behavior = GuardBehavior(behavior_str)
        passthrough_on_error = guard_config.get("passthrough_on_error", True)

        try:
            eval_context = self._prepare_eval_context(context)

            request = FilterItemRequest(data=eval_context, condition=clause)
            filter_result = self._filter.filter_item(request)

            filter_result = self._reclassify_missing_field_error(filter_result, clause)

            return GuardResult.from_filter_result(filter_result, behavior, passthrough_on_error)

        except (ValueError, TypeError, KeyError, AttributeError) as e:
            logger.warning("Guard: guard condition evaluation exception: %s", e)
            if passthrough_on_error:
                return GuardResult.passed()
            if behavior == GuardBehavior.WARN:
                return GuardResult.warned()
            if behavior == GuardBehavior.SKIP:
                return GuardResult.skipped(error=str(e))
            return GuardResult.filtered(error=str(e))

    def _reclassify_missing_field_error(
        self, filter_result: FilterResult, clause: str
    ) -> FilterResult:
        """Reclassify DATA errors for missing fields in namespaced content.

        With namespaced content, guard conditions must use dotted paths
        (e.g., ``validate.pass == false``).  Two cases are handled:

        1. **Flat field with namespace match** — the field exists inside a
           namespace but was referenced without the prefix.  Reclassified as
           SEMANTIC so the guard behavior always applies (bypasses
           ``passthrough_on_error``).
        2. **Genuinely missing field** — the field does not exist anywhere.
           Treated as *condition not matched* so the guard behavior applies
           instead of silently passing.
        """
        if (
            filter_result.success
            or filter_result.error_category != ErrorCategory.DATA
            or not filter_result.error
        ):
            return filter_result

        # Only reclassify MissingFieldError-originated errors
        if "does not exist in the data" not in filter_result.error:
            return filter_result

        if "Did you mean:" in filter_result.error:
            # Flat field reference that exists in a namespace → semantic error
            logger.warning(
                "Guard: flat field reference in condition '%s'. "
                "Content is namespaced — use dotted paths (e.g., action_name.field). %s",
                clause,
                filter_result.error,
            )
            return FilterResult(
                success=False,
                error=filter_result.error,
                error_category=ErrorCategory.SEMANTIC,
                execution_time=filter_result.execution_time,
            )

        # Field genuinely missing → treat as condition not matched
        logger.debug(
            "Guard: field not found in condition '%s', treating as not matched: %s",
            clause,
            filter_result.error,
        )
        return FilterResult(
            success=True,
            matched=False,
            error=filter_result.error,
            execution_time=filter_result.execution_time,
        )

    def _prepare_eval_context(self, context: Any) -> dict[str, Any]:
        """Promote content namespaces to top-level keys for guard evaluation.

        With namespaced content, each action's output is a nested dict::

            {"content": {"action_a": {"field": "val"}, "action_b": {...}}}

        After promotion, guard conditions use dotted paths to access fields::

            action_a.field == "val"
        """
        if isinstance(context, dict):
            if "content" in context and isinstance(context["content"], dict):
                result = {k: v for k, v in context.items() if k != "content"}
                result.update(context["content"])
                return result
            return context

        return {"_raw": context}

    def _build_evaluation_context(self, item: Any, context: dict[str, Any]) -> dict[str, Any]:
        """Merge item content with full context for Phase 2 evaluation.

        Namespaced content in ``item["content"]`` is promoted to top-level keys
        so guard conditions can use dotted paths (e.g., ``action.field``).
        """
        eval_data = {}

        if context:
            eval_data.update(context)

        if isinstance(item, dict):
            if "content" in item and isinstance(item["content"], dict):
                # Content fields take precedence over top-level fields
                for k, v in item.items():
                    if k != "content":
                        eval_data[k] = v
                eval_data.update(item["content"])
            else:
                eval_data.update(item)
        elif item is not None:
            eval_data["_raw"] = item

        return eval_data

    def should_skip(self, agent_config: dict[str, Any], context: Any) -> bool:
        """Check if agent should be skipped based on guard with skip behavior."""
        guard_config = agent_config.get("guard")
        if not guard_config or guard_config.get("behavior") != GuardBehavior.SKIP:
            return False

        result = self._evaluate_guard(context, guard_config)
        return not result.should_execute

    def should_filter(self, agent_config: dict[str, Any], context: Any) -> bool:
        """Check if item should be filtered based on guard with filter behavior."""
        guard_config = agent_config.get("guard")
        if not guard_config or guard_config.get("behavior") != GuardBehavior.FILTER:
            return False

        result = self._evaluate_guard(context, guard_config)
        return not result.should_execute


# Thread-safe singleton
_GLOBAL_GUARD_EVALUATOR: GuardEvaluator | None = None
_GUARD_EVALUATOR_LOCK = threading.Lock()


def get_guard_evaluator() -> GuardEvaluator:
    """Get the global GuardEvaluator instance (thread-safe)."""
    global _GLOBAL_GUARD_EVALUATOR
    if _GLOBAL_GUARD_EVALUATOR is None:
        with _GUARD_EVALUATOR_LOCK:
            if _GLOBAL_GUARD_EVALUATOR is None:
                _GLOBAL_GUARD_EVALUATOR = GuardEvaluator()
    return _GLOBAL_GUARD_EVALUATOR


def reset_guard_evaluator() -> None:
    """Reset the global GuardEvaluator instance (for testing)."""
    global _GLOBAL_GUARD_EVALUATOR
    _GLOBAL_GUARD_EVALUATOR = None
