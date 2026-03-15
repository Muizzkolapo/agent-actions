"""Filtering submodule - Dataset filtering logic."""

from agent_actions.input.preprocessing.filtering.evaluator import (
    GuardEvaluator,
    GuardResult,
    get_guard_evaluator,
    reset_guard_evaluator,
)
from agent_actions.input.preprocessing.filtering.guard_filter import (
    FilterItemRequest,
    FilterResult,
    GuardFilter,
    get_global_guard_filter,
    reset_global_guard_filter,
)

__all__ = [
    # Primary API (unified evaluator)
    "GuardEvaluator",
    "GuardResult",
    "get_guard_evaluator",
    "reset_guard_evaluator",
    # Low-level filter
    "GuardFilter",
    "FilterResult",
    "FilterItemRequest",
    "get_global_guard_filter",
    "reset_global_guard_filter",
]
