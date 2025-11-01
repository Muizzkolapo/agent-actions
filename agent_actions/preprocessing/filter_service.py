"""
Centralized filtering logic for WHERE clause and conditional clause evaluation.

This service consolidates filtering logic shared between batch and realtime modes,
eliminating ~100 lines of code duplication (Phase 1 of issue #492).

## Overview

FilterService provides a unified interface for evaluating WHERE clauses and conditional
clauses across both batch and realtime processing modes. It handles two filtering behaviors:
- **'filter' behavior**: Excludes items that don't match (removes from output)
- **'skip' behavior**: Marks non-matching items for passthrough (includes in output with metadata)

## Shared Usage

**Batch Mode** (`batch_service.py`):
```python
from agent_actions.preprocessing.filter_service import get_filter_service

filter_service = get_filter_service()

# Filter each item during batch preparation
for row in data:
    filter_status = filter_service.filter_single_item(
        item_content=row_content,
        where_clause_config=where_clause_config,
        conditional_clause=conditional_clause
    )

    # Track status in context map
    context_map[custom_id]['_batch_filter_status'] = filter_status.status

    if filter_status.should_include:
        prepared_data.append(item)
```

**Realtime Mode** (`target_content_processor.py`):
```python
from agent_actions.preprocessing.filter_service import get_filter_service

filter_service = get_filter_service()

# Filter entire dataset at once
filtered_data, status_map = filter_service.apply_where_clause_filtering(
    data=data,
    where_clause_config=where_clause_config,
    conditional_clause=conditional_clause
)

# Process filtered_data...
```

## Configuration

WHERE clause config structure:
```python
where_clause_config = {
    'clause': 'status == "active"',  # WHERE clause expression
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

- **ContextScopeProcessor**: Builds field context for WHERE clause evaluation
- **WhereClauseParser**: Parses and evaluates WHERE clause expressions
- **DataTransformer**: Handles passthrough field merging

## See Also

- Architecture docs: `dev_artefacts/BATCH_REALTIME_ARCHITECTURE.md`
- Tests: `tests/preprocessing/test_filter_service.py`
- Issue: https://github.com/Muizzkolapo/agent-actions/issues/492
"""

import logging
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass

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
        from agent_actions.response_processing.where_parser import get_global_filter
        self.where_filter = get_global_filter()

    def filter_single_item(
        self,
        item_content: Dict[str, Any],
        where_clause_config: Optional[Dict[str, Any]] = None,
        conditional_clause: Optional[str] = None
    ) -> FilterStatus:
        """
        Filter a single item using WHERE clause or conditional clause.

        Args:
            item_content: The content to evaluate (typically row['content'] or row)
            where_clause_config: WHERE clause configuration dict with keys:
                - 'clause': str - The WHERE clause expression
                - 'behavior': str - Either 'filter' or 'skip'
                - 'passthrough_on_error': bool - Whether to include items on error
            conditional_clause: Optional conditional clause (UDF name)

        Returns:
            FilterStatus indicating whether to include item and the status:
            - should_include=True, status='included': Process item normally
            - should_include=False, status='filtered': Exclude from output (WHERE filter)
            - should_include=False, status='skipped': Include as passthrough (WHERE skip)

        Usage:
            # Batch mode
            filter_status = filter_service.filter_single_item(
                row_content, where_clause_config
            )
            if filter_status.should_include:
                prepared_data.append(item)
            context_map[custom_id]['_batch_filter_status'] = filter_status.status

            # Realtime mode
            filter_status = filter_service.filter_single_item(
                item['content'], where_clause_config
            )
            if filter_status.should_include:
                filtered_data.append(item)
        """
        # Handle WHERE clause filtering
        if where_clause_config:
            scope = where_clause_config.get('scope', 'item')
            if scope == 'item':
                behavior = where_clause_config.get('behavior', 'filter')
                clause = where_clause_config.get('clause')
                passthrough_on_error = where_clause_config.get('passthrough_on_error', True)

                try:
                    logger.info(f"WHERE clause evaluation: '{clause}' (behavior: {behavior})")
                    filter_result = self.where_filter.filter_item(item_content, clause)

                    # Handle FilterResult object (from preprocessing/where_filter.py)
                    if hasattr(filter_result, 'success'):
                        logger.info(f'Filter result - success: {filter_result.success}, matched: {filter_result.matched}')

                        # Evaluation failed
                        if not filter_result.success:
                            if filter_result.error:
                                logger.warning(f'Filter error: {filter_result.error}')

                            if not passthrough_on_error:
                                # Error + passthrough_on_error=False
                                if behavior == 'filter':
                                    return FilterStatus(should_include=False, status='filtered', error=filter_result.error)
                                else:  # skip
                                    return FilterStatus(should_include=False, status='skipped', error=filter_result.error)
                            else:
                                # Error + passthrough_on_error=True: include item
                                return FilterStatus(should_include=True, status='included', error=filter_result.error)

                        # Evaluation succeeded but didn't match
                        elif not filter_result.matched:
                            logger.info(f'WHERE clause not matched')
                            if behavior == 'filter':
                                return FilterStatus(should_include=False, status='filtered')
                            else:  # skip
                                return FilterStatus(should_include=False, status='skipped')

                        # Evaluation succeeded and matched
                        else:
                            return FilterStatus(should_include=True, status='included')

                    # Handle boolean result (legacy SimpleWhereFilter)
                    else:
                        matched = bool(filter_result)
                        logger.info(f'Filter result (boolean): {matched}')

                        if not matched:
                            if behavior == 'filter':
                                return FilterStatus(should_include=False, status='filtered')
                            else:  # skip
                                return FilterStatus(should_include=False, status='skipped')
                        else:
                            return FilterStatus(should_include=True, status='included')

                except Exception as e:
                    logger.warning(f'Error in WHERE clause evaluation: {e}')

                    if not passthrough_on_error:
                        if behavior == 'filter':
                            return FilterStatus(should_include=False, status='filtered', error=str(e))
                        else:  # skip
                            return FilterStatus(should_include=False, status='skipped', error=str(e))
                    else:
                        # Passthrough on error
                        return FilterStatus(should_include=True, status='included', error=str(e))

        # Handle conditional clause (legacy feature)
        if conditional_clause:
            try:
                from agent_actions.utilities.tooling import execute_user_defined_function
                result = execute_user_defined_function(conditional_clause, item_content)

                if not result:
                    logger.info(f'Conditional clause failed: {conditional_clause}')
                    return FilterStatus(should_include=False, status='skipped')
                else:
                    return FilterStatus(should_include=True, status='included')

            except Exception as e:
                logger.warning(f'Error in conditional clause evaluation: {e}')
                # Conditional clauses always passthrough on error (legacy behavior)
                return FilterStatus(should_include=True, status='included', error=str(e))

        # No filtering configured
        return FilterStatus(should_include=True, status='included')

    def apply_where_clause_filtering(
        self,
        data: List[Dict[str, Any]],
        where_clause_config: Optional[Dict[str, Any]] = None,
        conditional_clause: Optional[str] = None,
        content_key: str = 'content'
    ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        """
        Apply WHERE clause filtering to a list of data items (realtime mode).

        Args:
            data: List of data items to filter (each with 'content' and 'target_id')
            where_clause_config: WHERE clause configuration
            conditional_clause: Optional conditional clause
            content_key: Key to extract content for evaluation (default: 'content')

        Returns:
            Tuple of (filtered_data, status_map):
            - filtered_data: Items that should be included
            - status_map: Dict mapping target_id to filter status

        Usage (realtime mode):
            filtered_data, status_map = filter_service.apply_where_clause_filtering(
                data, where_clause_config
            )
            # Process filtered_data...
        """
        filtered_data = []
        status_map = {}

        for item in data:
            target_id = item.get('target_id', 'unknown')
            item_content = item.get(content_key, item)

            filter_status = self.filter_single_item(
                item_content,
                where_clause_config,
                conditional_clause
            )

            status_map[target_id] = filter_status.status

            if filter_status.should_include:
                filtered_data.append(item)

        return filtered_data, status_map


# Global instance for convenience
_global_filter_service = None


def get_filter_service() -> FilterService:
    """Get the global FilterService instance."""
    global _global_filter_service
    if _global_filter_service is None:
        _global_filter_service = FilterService()
    return _global_filter_service
