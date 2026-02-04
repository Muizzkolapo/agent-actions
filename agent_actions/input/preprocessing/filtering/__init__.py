"""Filtering submodule - Dataset filtering logic."""

from agent_actions.input.preprocessing.filtering.evaluator import (
    GuardEvaluator,
    GuardResult,
    get_guard_evaluator,
    reset_guard_evaluator,
)
from agent_actions.input.preprocessing.filtering.guard_handler import (
    GuardHandler,
    GuardConfig,
    GuardFilteringContext,
    get_guard_handler,
)
from agent_actions.input.preprocessing.filtering.guard_filter import (
    GuardFilter,
    FilterResult,
    FilterItemRequest,
    get_global_guard_filter,
)
from agent_actions.input.preprocessing.filtering.service import (
    FilterService,
    FilterStatus,
    get_filter_service,
)

__all__ = [
    # Primary API (new unified evaluator)
    "GuardEvaluator",
    "GuardResult",
    "get_guard_evaluator",
    "reset_guard_evaluator",
    # Orchestration layer
    "GuardHandler",
    "GuardConfig",
    "GuardFilteringContext",
    "get_guard_handler",
    # Low-level filter
    "GuardFilter",
    "FilterResult",
    "FilterItemRequest",
    "get_global_guard_filter",
    # Service layer (being consolidated)
    "FilterService",
    "FilterStatus",
    "get_filter_service",
]
