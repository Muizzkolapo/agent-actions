"""
Centralized filtering logic for guard condition and conditional clause evaluation.

This service consolidates filtering logic shared between batch and realtime modes,
eliminating ~100 lines of code duplication (Phase 1 of issue #492).

## Overview

FilterService provides a unified interface for evaluating guard conditions and conditional
clauses across both batch and realtime processing modes. It handles two filtering behaviors:
- **'filter' behavior**: Excludes items that don't match (removes from output)
- **'skip' behavior**: Marks non-matching items for passthrough (includes in output with metadata)

## Shared Usage

**Batch Mode** (`batch_service.py`):
```python
from agent_actions.preprocessing.filtering.filter_service import get_filter_service

filter_service = get_filter_service()

# Filter each item during batch preparation
for row in data:
    filter_status = filter_service.filter_single_item(
        item_content=row_content,
        guard_config=guard_config,
        conditional_clause=conditional_clause
    )

    # Track status in context map
    context_map[custom_id]['_batch_filter_status'] = filter_status.status

    if filter_status.should_include:
        prepared_data.append(item)
```

**Realtime Mode** (`target_content_processor.py`):
```python
from agent_actions.preprocessing.filtering.filter_service import get_filter_service

filter_service = get_filter_service()

# Filter entire dataset at once
filtered_data, status_map = filter_service.apply_guard_filtering(
    data=data,
    guard_config=guard_config,
    conditional_clause=conditional_clause
)

# Process filtered_data...
```

## Configuration

Guard config structure:
```python
guard_config = {
    'clause': 'status == "active"',  # Guard condition expression
    'scope': 'item',                  # Scope of evaluation
    'behavior': 'filter',             # 'filter' or 'skip'
    'passthrough_on_error': True      # Include items on error (default: True)
}
```

## Filter Behaviors

### 'filter' Behavior
Items that don't match are **excluded** from output:
- `should_include=False, status='filtered'`
- Item will not appear in results
- Used when you want to process only matching items

### 'skip' Behavior
Items that don't match are **marked for passthrough**:
- `should_include=False, status='skipped'`
- Item appears in output with `skipped_by_conditional=True` metadata
- Used when you want to preserve non-matching items

## Error Handling

By default, `passthrough_on_error=True`:
- Items that error during evaluation are **included** (fail-open)
- Error is logged but doesn't stop processing
- Set `passthrough_on_error=False` for strict error handling

## Benefits

1. **Single Source of Truth** - Changes to filtering logic in ONE place
2. **Consistent Behavior** - Batch and realtime use identical logic
3. **Comprehensive Testing** - 21 unit tests covering all scenarios
4. **Backward Compatible** - Supports legacy conditional clauses

## Related Components

- **ContextScopeProcessor**: Builds field context for guard evaluation
- **WhereClauseParser**: Parses and evaluates guard condition expressions
- **DataTransformer**: Handles passthrough field merging

## See Also

- Architecture docs: `dev_artefacts/BATCH_REALTIME_ARCHITECTURE.md`
- Tests: `tests/preprocessing/test_filter_service.py`
- Issue: https://github.com/Muizzkolapo/agent-actions/issues/492
"""

import logging
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass

from agent_actions.preprocessing.filtering.guard_filter import (
    get_global_guard_filter,
    FilterItemRequest,
)
from agent_actions.utilities.udf_management.tooling import execute_user_defined_function

logger = logging.getLogger(__name__)


@dataclass
class FilterStatus:
    """Result of filtering a single item."""

    should_include: bool  # Whether item should be processed
    status: str  # 'included', 'filtered', or 'skipped'
    error: Optional[str] = None


class FilterService:
    """
    Centralized filtering service for WHERE clause and conditional clause evaluation.

    This service is shared between batch mode (batch_service.py) and realtime mode
    (target_content_processor.py) to eliminate code duplication and ensure consistent
    filtering behavior.
    """

    def __init__(self):
        """Initialize the filter service."""
        self.guard_filter = get_global_guard_filter()

    def _handle_filter_result_object(
        self, filter_result, behavior: str, passthrough_on_error: bool
    ) -> FilterStatus:
        """Handle FilterResult object from where_filter."""
        logger.info(
            "Filter result - success: %s, matched: %s", filter_result.success, filter_result.matched
        )

        # Evaluation failed
        if not filter_result.success:
            if filter_result.error:
                logger.warning("Filter error: %s", filter_result.error)
            return self._handle_evaluation_error(
                filter_result.error, behavior, passthrough_on_error
            )

        # Evaluation succeeded but didn't match
        if not filter_result.matched:
            logger.info("WHERE clause not matched")
            status = "filtered" if behavior == "filter" else "skipped"
            return FilterStatus(should_include=False, status=status)

        # Evaluation succeeded and matched
        return FilterStatus(should_include=True, status="included")

    def _handle_evaluation_error(
        self, error: Optional[str], behavior: str, passthrough_on_error: bool
    ) -> FilterStatus:
        """Handle evaluation errors with passthrough logic."""
        if not passthrough_on_error:
            status = "filtered" if behavior == "filter" else "skipped"
            return FilterStatus(should_include=False, status=status, error=error)
        # Error + passthrough_on_error=True: include item
        return FilterStatus(should_include=True, status="included", error=error)

    def _evaluate_guard(
        self, item_content: Dict[str, Any], guard_config: Dict[str, Any]
    ) -> FilterStatus:
        """Evaluate guard condition for item."""
        scope = guard_config.get("scope", "item")
        if scope != "item":
            return FilterStatus(should_include=True, status="included")

        behavior = guard_config.get("behavior", "filter")
        clause = guard_config.get("clause")
        passthrough_on_error = guard_config.get("passthrough_on_error", True)

        try:
            logger.info("Guard condition evaluation: '%s' (behavior: %s)", clause, behavior)
            request = FilterItemRequest(data=item_content, condition=clause)
            filter_result = self.guard_filter.filter_item(request)

            # Modern GuardFilter always returns FilterResult object
            return self._handle_filter_result_object(filter_result, behavior, passthrough_on_error)

        except ValueError as e:
            logger.warning("Error in guard condition evaluation: %s", e)
            return self._handle_evaluation_error(str(e), behavior, passthrough_on_error)

    def _evaluate_conditional_clause(
        self, item_content: Dict[str, Any], conditional_clause: str
    ) -> FilterStatus:
        """Evaluate conditional clause for item."""
        try:
            result = execute_user_defined_function(conditional_clause, item_content)

            if not result:
                logger.info("Conditional clause failed: %s", conditional_clause)
                return FilterStatus(should_include=False, status="skipped")
            return FilterStatus(should_include=True, status="included")

        except ValueError as e:
            logger.warning("Error in conditional clause evaluation: %s", e)
            # Conditional clauses always passthrough on error (legacy behavior)
            return FilterStatus(should_include=True, status="included", error=str(e))

    def filter_single_item(
        self,
        item_content: Dict[str, Any],
        guard_config: Optional[Dict[str, Any]] = None,
        conditional_clause: Optional[str] = None,
    ) -> FilterStatus:
        """
        Filter a single item using guard condition or conditional clause.

        Args:
            item_content: The content to evaluate (typically row['content'] or row)
            guard_config: Guard configuration dict with keys:
                - 'clause': str - The guard condition expression
                - 'behavior': str - Either 'filter' or 'skip'
                - 'passthrough_on_error': bool - Whether to include items on error
            conditional_clause: Optional conditional clause (UDF name)

        Returns:
            FilterStatus indicating whether to include item and the status:
            - should_include=True, status='included': Process item normally
            - should_include=False, status='filtered': Exclude from output (guard filter)
            - should_include=False, status='skipped': Include as passthrough (guard skip)

        Usage:
            # Batch mode
            filter_status = filter_service.filter_single_item(
                row_content, guard_config
            )
            if filter_status.should_include:
                prepared_data.append(item)
            context_map[custom_id]['_batch_filter_status'] = filter_status.status

            # Realtime mode
            filter_status = filter_service.filter_single_item(
                item['content'], guard_config
            )
            if filter_status.should_include:
                filtered_data.append(item)
        """
        # Handle guard condition filtering
        if guard_config:
            return self._evaluate_guard(item_content, guard_config)

        # Handle conditional clause (legacy feature)
        if conditional_clause:
            return self._evaluate_conditional_clause(item_content, conditional_clause)

        # No filtering configured
        return FilterStatus(should_include=True, status="included")

    def apply_guard_filtering(
        self,
        data: List[Dict[str, Any]],
        guard_config: Optional[Dict[str, Any]] = None,
        conditional_clause: Optional[str] = None,
        content_key: str = "content",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        """
        Apply guard filtering to a list of data items (realtime mode).

        Args:
            data: List of data items to filter (each with 'content' and 'target_id')
            guard_config: Guard configuration
            conditional_clause: Optional conditional clause
            content_key: Key to extract content for evaluation (default: 'content')

        Returns:
            Tuple of (filtered_data, status_map):
            - filtered_data: Items that should be included
            - status_map: Dict mapping target_id to filter status

        Usage (realtime mode):
            filtered_data, status_map = filter_service.apply_guard_filtering(
                data, guard_config
            )
            # Process filtered_data...
        """
        filtered_data = []
        status_map = {}

        for item in data:
            target_id = item.get("target_id", "unknown")
            item_content = item.get(content_key, item)

            filter_status = self.filter_single_item(item_content, guard_config, conditional_clause)

            status_map[target_id] = filter_status.status

            if filter_status.should_include:
                filtered_data.append(item)

        return filtered_data, status_map


# Global instance for convenience
_GLOBAL_FILTER_SERVICE = None


def get_filter_service() -> FilterService:
    """Get the global FilterService instance."""
    global _GLOBAL_FILTER_SERVICE  # pylint: disable=global-statement
    if _GLOBAL_FILTER_SERVICE is None:
        _GLOBAL_FILTER_SERVICE = FilterService()
    return _GLOBAL_FILTER_SERVICE
