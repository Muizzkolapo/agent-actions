"""
Unified guard evaluation for batch and online modes.

This module consolidates the 4 guard implementations:
- GuardFilter (AST engine)
- FilterService (business logic)
- GuardHandler (orchestration)
- helpers._evaluate_guard (LLM layer)

Into a single GuardEvaluator that supports two-phase evaluation:
- Phase 1 (Early): Before prompt preparation, on raw content only
- Phase 2 (With Context): After prompt preparation, with passthrough fields

Related: GitHub Issue #875, #888
"""

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from agent_actions.input.preprocessing.filtering.guard_filter import (
    get_global_guard_filter,
    FilterItemRequest,
    GuardFilter,
    FilterResult,
)
from agent_actions.utils.udf_management.tooling import execute_user_defined_function

logger = logging.getLogger(__name__)


@dataclass
class GuardResult:
    """
    Result of guard evaluation.

    Attributes:
        should_execute: Whether the item should be processed
        behavior: The behavior that caused non-execution ('skip' or 'filter'), or None if passed
        error: Error message if evaluation failed
        matched: Whether the guard condition matched (True = passed)
    """

    should_execute: bool
    behavior: Optional[str] = None  # 'skip' | 'filter' | None
    error: Optional[str] = None
    matched: bool = True

    @classmethod
    def passed(cls) -> "GuardResult":
        """Guard passed - item should be executed."""
        return cls(should_execute=True, matched=True)

    @classmethod
    def skipped(cls, error: Optional[str] = None) -> "GuardResult":
        """Guard failed with skip behavior - use passthrough."""
        return cls(should_execute=False, behavior="skip", matched=False, error=error)

    @classmethod
    def filtered(cls, error: Optional[str] = None) -> "GuardResult":
        """Guard failed with filter behavior - exclude entirely."""
        return cls(should_execute=False, behavior="filter", matched=False, error=error)

    @classmethod
    def from_filter_result(
        cls, filter_result: FilterResult, behavior: str, passthrough_on_error: bool
    ) -> "GuardResult":
        """
        Create GuardResult from FilterResult.

        Args:
            filter_result: Result from GuardFilter.filter_item()
            behavior: Guard behavior ('skip' or 'filter')
            passthrough_on_error: Whether to proceed on evaluation error
        """
        # Evaluation failed
        if not filter_result.success:
            if passthrough_on_error:
                logger.debug(
                    "Guard: condition evaluation failed, proceeding (passthrough_on_error=True)"
                )
                return cls.passed()
            logger.debug(
                "Guard: condition evaluation failed, applying behavior '%s' (passthrough_on_error=False)",
                behavior,
            )
            if behavior == "skip":
                return cls.skipped(error=filter_result.error)
            return cls.filtered(error=filter_result.error)

        # Evaluation succeeded but didn't match
        if not filter_result.matched:
            logger.debug("Guard: condition not matched, behavior='%s'", behavior)
            if behavior == "skip":
                return cls.skipped()
            return cls.filtered()

        # Evaluation succeeded and matched
        return cls.passed()


class GuardEvaluator:
    """
    Unified guard evaluation with two-phase support.

    This class consolidates guard evaluation logic that was previously spread across:
    - processing/helpers.py (evaluate_guard_condition, _evaluate_guard, etc.)
    - filtering/service.py (FilterService._evaluate_guard)
    - filtering/guard_handler.py (GuardHandler.filter_single_item)

    Two-Phase Strategy:
    - Phase 1 (evaluate_early): Evaluates guards on raw content BEFORE prompt preparation.
      Cannot access passthrough fields or {source.*} references.
      Used to skip expensive operations early.

    - Phase 2 (evaluate_with_context): Evaluates guards AFTER prompt preparation.
      Can access passthrough fields and full prompt context.
      Used at LLM layer for final decision.

    Usage:
        evaluator = get_guard_evaluator()

        # Phase 1: Early check
        result = evaluator.evaluate_early(item, guard_config)
        if not result.should_execute:
            return handle_skip_or_filter(result)

        # ... prepare prompt ...

        # Phase 2: Full context check (optional, for context-dependent guards)
        result = evaluator.evaluate_with_context(item, guard_config, full_context)
        if not result.should_execute:
            return handle_skip_or_filter(result)
    """

    def __init__(self, guard_filter: Optional[GuardFilter] = None):
        """
        Initialize GuardEvaluator.

        Args:
            guard_filter: Optional GuardFilter instance. Uses global instance if not provided.
        """
        self._filter = guard_filter or get_global_guard_filter()

    def evaluate_early(
        self,
        item: Any,
        guard_config: Optional[Dict[str, Any]],
        conditional_clause: Optional[str] = None,
    ) -> GuardResult:
        """
        Phase 1: Early evaluation before expensive operations.

        Evaluates guards on raw content only. Cannot access:
        - Passthrough fields (not computed yet)
        - {source.*} references (not resolved yet)

        Use this to skip unnecessary prompt preparation for items that
        would be filtered/skipped anyway.

        Args:
            item: Data item to evaluate (dict or raw content)
            guard_config: Guard configuration dict with keys:
                - 'clause': str - The guard condition expression
                - 'behavior': str - Either 'filter' or 'skip'
                - 'scope': str - 'item' or 'agent'
                - 'passthrough_on_error': bool - Whether to proceed on error
            conditional_clause: Optional legacy UDF conditional clause

        Returns:
            GuardResult indicating whether to proceed with execution
        """
        # Check legacy conditional clause first (UDF-based)
        if conditional_clause:
            result = self._evaluate_conditional_clause(item, conditional_clause)
            if result is not None:
                return result

        # Check guard condition
        return self._evaluate_guard(item, guard_config)

    def evaluate_with_context(
        self,
        item: Any,
        guard_config: Optional[Dict[str, Any]],
        context: Dict[str, Any],
        conditional_clause: Optional[str] = None,
    ) -> GuardResult:
        """
        Phase 2: Evaluation with full context.

        Evaluates guards with access to:
        - Passthrough fields (computed during prompt prep)
        - Full prompt context including {source.*} references

        Use this at LLM layer for guards that reference context-dependent fields.

        Args:
            item: Original data item
            guard_config: Guard configuration dict
            context: Full context including passthrough fields and source data
            conditional_clause: Optional legacy UDF conditional clause

        Returns:
            GuardResult indicating whether to proceed with execution
        """
        # Merge item content with context for evaluation
        eval_data = self._build_evaluation_context(item, context)

        # Check legacy conditional clause first
        if conditional_clause:
            result = self._evaluate_conditional_clause(eval_data, conditional_clause)
            if result is not None:
                return result

        # Check guard condition with full context
        return self._evaluate_guard(eval_data, guard_config)

    def evaluate(
        self,
        item: Any,
        guard_config: Optional[Dict[str, Any]],
        conditional_clause: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Backward-compatible evaluation returning tuple format.

        This method provides compatibility with existing code that expects
        (should_execute, behavior) tuple format.

        Args:
            item: Data item to evaluate
            guard_config: Guard configuration dict
            conditional_clause: Optional legacy UDF conditional clause

        Returns:
            Tuple of (should_execute, skip_behavior):
            - (True, None) = guard passed, proceed with execution
            - (False, 'skip') = guard failed with skip behavior
            - (False, 'filter') = guard failed with filter behavior
        """
        result = self.evaluate_early(item, guard_config, conditional_clause)
        return (result.should_execute, result.behavior)

    def _evaluate_conditional_clause(
        self, context: Any, conditional_clause: str
    ) -> Optional[GuardResult]:
        """
        Evaluate legacy conditional clause (UDF-based).

        Returns None if no conditional clause or if it passes.
        Returns GuardResult.skipped() if it fails.
        """
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

    def _evaluate_guard(self, context: Any, guard_config: Optional[Dict[str, Any]]) -> GuardResult:
        """
        Evaluate guard condition.

        Args:
            context: Data to evaluate against
            guard_config: Guard configuration

        Returns:
            GuardResult indicating evaluation outcome
        """
        if not guard_config:
            return GuardResult.passed()

        # Check scope - only evaluate item-level guards
        scope = guard_config.get("scope", "item")
        if scope != "item":
            return GuardResult.passed()

        clause = guard_config.get("clause")
        if not clause:
            return GuardResult.passed()

        behavior = guard_config.get("behavior", "filter")
        passthrough_on_error = guard_config.get("passthrough_on_error", True)

        try:
            # Prepare context for evaluation
            eval_context = self._prepare_eval_context(context)

            request = FilterItemRequest(data=eval_context, condition=clause)
            filter_result = self._filter.filter_item(request)

            return GuardResult.from_filter_result(filter_result, behavior, passthrough_on_error)

        except (ValueError, TypeError, KeyError, AttributeError) as e:
            logger.warning("Guard: guard condition evaluation exception: %s", e)
            if passthrough_on_error:
                return GuardResult.passed()
            if behavior == "skip":
                return GuardResult.skipped(error=str(e))
            return GuardResult.filtered(error=str(e))

    def _prepare_eval_context(self, context: Any) -> Dict[str, Any]:
        """
        Prepare context for guard evaluation.

        Handles nested structures and ensures we have a dict for evaluation.
        When context has nested {"content": {...}}, we merge ALL top-level
        metadata with the content dict so guards can access both.
        """
        if isinstance(context, dict):
            # Handle nested content structure
            if "content" in context and isinstance(context["content"], dict):
                # Start with all top-level metadata (preserves lineage, custom fields, etc.)
                result = {k: v for k, v in context.items() if k != "content"}
                # Merge content fields (content fields override top-level if conflicts)
                result.update(context["content"])
                return result
            return context

        # Wrap non-dict in _raw key
        return {"_raw": context}

    def _build_evaluation_context(self, item: Any, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build evaluation context by merging item with full context.

        For Phase 2 evaluation, combines:
        - Current item content (at top level for backward compat)
        - Full context including passthrough fields, source data, etc.

        Non-dict items are wrapped in {"_raw": item} to maintain parity
        with evaluate_early behavior.
        """
        eval_data = {}

        # Add full context first
        if context:
            eval_data.update(context)

        # Add/override with item content
        if isinstance(item, dict):
            if "content" in item and isinstance(item["content"], dict):
                # Preserve ALL top-level fields (like doc_type, source_guid)
                # then merge content fields on top (content takes precedence)
                for k, v in item.items():
                    if k != "content":
                        eval_data[k] = v
                eval_data.update(item["content"])
            else:
                eval_data.update(item)
        elif item is not None:
            # Preserve non-dict items in _raw key (matches _prepare_eval_context behavior)
            eval_data["_raw"] = item

        return eval_data

    def should_skip(self, agent_config: Dict[str, Any], context: Any) -> bool:
        """
        Check if agent should be skipped based on guard with skip behavior.

        Backward-compatible method for run_dynamic_agent().

        Args:
            agent_config: Agent configuration with guard
            context: Data context for evaluation

        Returns:
            True if agent should be skipped (guard not matched with skip behavior)
        """
        guard_config = agent_config.get("guard")
        if not guard_config or guard_config.get("behavior") != "skip":
            return False

        result = self._evaluate_guard(context, guard_config)
        return not result.should_execute

    def should_filter(self, agent_config: Dict[str, Any], context: Any) -> bool:
        """
        Check if item should be filtered based on guard with filter behavior.

        Backward-compatible method for run_dynamic_agent().

        Args:
            agent_config: Agent configuration with guard
            context: Data context for evaluation

        Returns:
            True if item should be filtered (guard not matched with filter behavior)
        """
        guard_config = agent_config.get("guard")
        if not guard_config or guard_config.get("behavior") != "filter":
            return False

        result = self._evaluate_guard(context, guard_config)
        return not result.should_execute


# Global instance for convenience (thread-safe initialization)
_GLOBAL_GUARD_EVALUATOR: Optional[GuardEvaluator] = None
_GUARD_EVALUATOR_LOCK = threading.Lock()


def get_guard_evaluator() -> GuardEvaluator:
    """Get the global GuardEvaluator instance (thread-safe)."""
    global _GLOBAL_GUARD_EVALUATOR
    if _GLOBAL_GUARD_EVALUATOR is None:
        with _GUARD_EVALUATOR_LOCK:
            # Double-checked locking pattern
            if _GLOBAL_GUARD_EVALUATOR is None:
                _GLOBAL_GUARD_EVALUATOR = GuardEvaluator()
    return _GLOBAL_GUARD_EVALUATOR


def reset_guard_evaluator() -> None:
    """Reset the global GuardEvaluator instance (for testing)."""
    global _GLOBAL_GUARD_EVALUATOR
    _GLOBAL_GUARD_EVALUATOR = None
