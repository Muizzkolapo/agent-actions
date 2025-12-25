"""
Unified WHERE clause handling across batch and online modes.

This module provides a consolidated interface for WHERE clause filtering that eliminates
duplication between batch and online workflows. It coordinates with FilterService for
expression evaluation while adding mode-specific behaviors and context tracking.

## Overview

WhereClauseHandler bridges FilterService (evaluation) with mode-specific orchestration
(batch task preparation vs online dataset filtering).

## Architecture

```
WhereClauseHandler (this module) - Unified orchestration interface
    │
    └──> FilterService - Expression evaluation engine
             └──> WhereClauseParser - SQL-like WHERE clause parsing
```

## Usage

**Batch Mode** (per-item with full context tracking):
```python
from agent_actions.preprocessing.filtering.where_clause_handler import WhereClauseHandler
from agent_actions.preprocessing.filtering.filter_service import get_filter_service

handler = WhereClauseHandler(get_filter_service())

# Process items individually with context tracking
for item in items:
    should_include, status = handler.filter_single_item(
        item, where_config, conditional_clause
    )

    if should_include:
        prepared_tasks.append(prepare_task(item))

    # Track for analytics
    context_map[item['target_id']]['_batch_filter_status'] = status
```

**Online Mode** (bulk pre-filtering):
```python
handler = WhereClauseHandler(get_filter_service())

# Bulk filter dataset
filtered_items, context = handler.filter_items_online_mode(
    items, where_config
)

# Process filtered items
for item in filtered_items:
    process(item)
```

## Key Design Decisions

1. **Timing Difference**: Batch pre-computes all filtering; online does bulk pre-filter
   - Rationale: Batch needs full context before submission; online streams processing

2. **Context Tracking**: Batch tracks all items; online only tracks at boundary
   - Rationale: Batch needs analytics; online optimizes for throughput

3. **Skip Behavior**: Batch handles uniformly; online splits filter/skip
   - Rationale: Online generator handles skip downstream for streaming

## Related Components

- FilterService: Core evaluation engine
- BatchTaskPreparator: Uses batch mode filtering
- TargetContentProcessor: Uses online mode filtering
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any
from enum import Enum

from agent_actions.preprocessing.filtering.filter_service import get_filter_service
from agent_actions.utilities.field_management.field_manager import FieldManager

logger = logging.getLogger(__name__)


class FilterBehavior(Enum):
    """Filter behavior options."""
    FILTER = 'filter'  # Exclude non-matching items
    SKIP = 'skip'      # Include non-matching as passthrough


@dataclass
class WhereClauseConfig:
    """Validated WHERE clause configuration."""
    clause: str
    scope: str = 'item'
    behavior: FilterBehavior = FilterBehavior.FILTER
    passthrough_on_error: bool = True

    @staticmethod
    def from_dict(config: Optional[Dict[str, Any]]) -> Optional['WhereClauseConfig']:
        """Create WhereClauseConfig from dict, returns None if invalid."""
        if not config or not config.get('clause'):
            return None

        try:
            behavior_str = config.get('behavior', 'filter')
            behavior = (
                FilterBehavior(behavior_str)
                if isinstance(behavior_str, str)
                else behavior_str
            )

            return WhereClauseConfig(
                clause=config.get('clause'),
                scope=config.get('scope', 'item'),
                behavior=behavior,
                passthrough_on_error=config.get('passthrough_on_error', True)
            )
        except (ValueError, TypeError) as e:
            logger.warning("Invalid WHERE clause config: %s", e)
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for FilterService compatibility."""
        return {
            'clause': self.clause,
            'scope': self.scope,
            'behavior': (
                self.behavior.value
                if isinstance(self.behavior, FilterBehavior)
                else self.behavior
            ),
            'passthrough_on_error': self.passthrough_on_error
        }


@dataclass
class WhereClauseFilteringContext:
    """
    Unified filtering context tracking for both modes.

    Tracks filtering decisions and provides analytics about what was filtered, skipped, etc.
    Used primarily in batch mode for comprehensive statistics; optional in online mode.
    """
    total_items: int
    included_items: int = 0
    filtered_items: int = 0
    skipped_items: int = 0
    error_items: int = 0
    item_results: Dict[str, str] = field(default_factory=dict)  # target_id -> status

    def track(self, target_id: str, status: str, has_error: bool = False):
        """
        Track filtering decision for an item.

        Args:
            target_id: Unique identifier for the item
            status: Filter status ('included', 'filtered', 'skipped')
            has_error: Whether filtering encountered an error
        """
        self.item_results[target_id] = status

        if status == 'filtered':
            self.filtered_items += 1
        elif status == 'skipped':
            self.skipped_items += 1
        elif status == 'included':
            self.included_items += 1

        if has_error:
            self.error_items += 1

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        return {
            'total_items': self.total_items,
            'included_items': self.included_items,
            'filtered_items': self.filtered_items,
            'skipped_items': self.skipped_items,
            'error_items': self.error_items,
            'success_rate': self.included_items / self.total_items if self.total_items > 0 else 0.0
        }


class WhereClauseHandler:
    """
    Unified WHERE clause filtering coordinator for batch and online modes.

    This class provides a consistent interface for WHERE clause filtering across
    both execution modes while respecting mode-specific timing and behavior differences.

    Mode Differences:
    - Batch: Per-item filtering with full context tracking before task submission
    - Online: Bulk dataset filtering with selective context tracking
    """

    def __init__(self, filter_service: 'FilterService'):
        """
        Initialize WHERE clause handler.

        Args:
            filter_service: FilterService instance for expression evaluation
        """
        self.filter_service = filter_service

    def validate_config(self, where_config: Optional[Dict]) -> Optional[WhereClauseConfig]:
        """
        Validate and normalize WHERE clause config.

        Args:
            where_config: Raw WHERE clause configuration dict

        Returns:
            Validated WhereClauseConfig or None if invalid/missing

        Raises:
            ValueError: If config is present but invalid
        """
        if not where_config:
            return None

        config = WhereClauseConfig.from_dict(where_config)
        if config is None and where_config.get('clause'):
            # Config present but invalid
            raise ValueError(f"Invalid WHERE clause configuration: {where_config}")

        return config

    def should_evaluate_at_item_level(self, config: Optional[WhereClauseConfig]) -> bool:
        """
        Check if WHERE clause applies at item level.

        Args:
            config: Validated WHERE clause configuration

        Returns:
            True if filtering should be applied per-item, False otherwise
        """
        return config is not None and config.scope == 'item'

    def filter_single_item(
        self,
        item: Dict,
        where_config: Optional[Dict],
        conditional_clause: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Filter single item (batch mode pattern).

        Args:
            item: Data item to filter (expects 'content' key or uses full dict)
            where_config: WHERE clause configuration dict
            conditional_clause: Optional conditional clause (legacy UDF support)

        Returns:
            Tuple of (should_include: bool, status: str)
            - should_include: Whether item should be processed
            - status: 'included', 'filtered', or 'skipped'

        Usage:
            handler = WhereClauseHandler(get_filter_service())
            should_include, status = handler.filter_single_item(
                row, where_config, conditional_clause
            )

            if should_include:
                tasks.append(prepare_task(row))

            context_map[target_id]['_batch_filter_status'] = status
        """
        config = self.validate_config(where_config)

        # No filtering configured
        if not self.should_evaluate_at_item_level(config) and not conditional_clause:
            return True, 'included'

        # Extract content for evaluation
        item_content = item.get('content', item)

        # Delegate to FilterService
        filter_result = self.filter_service.filter_single_item(
            item_content,
            config.to_dict() if config else None,
            conditional_clause
        )

        return filter_result.should_include, filter_result.status

    def filter_single_item_with_context(
        self,
        item: Dict,
        where_config: Optional[Dict],
        field_context: Optional[Dict] = None,
        conditional_clause: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Filter single item WITH full upstream context access.

        This enhanced method allows WHERE clauses to reference upstream action
        fields directly (e.g., "extract_facts.count > 5") without requiring
        those fields to be declared in context_scope.

        Args:
            item: Data item to filter (expects 'content' key or uses full dict)
            where_config: WHERE clause configuration dict
            field_context: Upstream action data {action_name: {field: value}}
            conditional_clause: Optional conditional clause (legacy UDF support)

        Returns:
            Tuple of (should_include: bool, status: str)

        Example:
            # Build field_context with upstream data
            field_context = {
                'extract_facts': {'count': 10, 'facts': [...]},
                'source': {'type': 'pdf', 'title': 'My Document'}
            }

            # Now guards can access upstream fields!
            should_include, status = handler.filter_single_item_with_context(
                item={'content': {'status': 'active'}},
                where_config={'clause': 'extract_facts.count > 5', 'scope': 'item'},
                field_context=field_context
            )
            # WHERE clause "extract_facts.count > 5" evaluates to True
        """
        config = self.validate_config(where_config)

        # No filtering configured
        if not self.should_evaluate_at_item_level(config) and not conditional_clause:
            return True, 'included'

        # Extract current item content
        item_content = item.get('content', item)

        # Build evaluation data with upstream context access
        if field_context:
            # Create evaluation dict that merges:
            # 1. Current item content (top-level for backward compat)
            # 2. Upstream action data (namespaced by action name)
            eval_data = {}

            # Add current item content at top level
            if isinstance(item_content, dict):
                eval_data.update(item_content)

            # Add upstream action data under action names
            # This enables "action_name.field" access in WHERE clauses
            for action_name, action_data in field_context.items():
                if action_name not in eval_data:  # Don't overwrite current content
                    eval_data[action_name] = action_data

            logger.debug(
                "Evaluating WHERE clause with upstream context. "
                "Actions available: %s",
                list(field_context.keys())
            )
        else:
            # No field context - use item content only (original behavior)
            eval_data = item_content

        # Delegate to FilterService
        filter_result = self.filter_service.filter_single_item(
            eval_data,
            config.to_dict() if config else None,
            conditional_clause
        )

        return filter_result.should_include, filter_result.status

    def filter_items_batch_mode(
        self,
        items: List[Dict],
        where_config: Optional[Dict],
        conditional_clause: Optional[str] = None
    ) -> Tuple[List[Dict], WhereClauseFilteringContext]:
        """
        Filter items for batch mode with full context tracking.

        Pre-computes all filtering before task submission. Tracks comprehensive
        statistics for analytics and debugging.

        Args:
            items: Data items to filter
            where_config: WHERE clause configuration dict
            conditional_clause: Optional conditional clause

        Returns:
            Tuple of (filtered_items, context):
            - filtered_items: Items that should be included
            - context: WhereClauseFilteringContext with statistics

        Usage:
            handler = WhereClauseHandler(get_filter_service())
            filtered, context = handler.filter_items_batch_mode(
                data, where_config
            )

            logger.info(f"Filtered {context.filtered_items} items")

            for item in filtered:
                prepare_batch_task(item)
        """
        context = WhereClauseFilteringContext(total_items=len(items))
        config = self.validate_config(where_config)

        # No filtering configured
        if not self.should_evaluate_at_item_level(config) and not conditional_clause:
            context.included_items = len(items)
            return items, context

        filtered_items = []

        for item in items:
            target_id = item.get('target_id', 'unknown')
            should_include, status = self.filter_single_item(
                item, where_config, conditional_clause
            )

            # Track decision
            context.track(target_id, status)

            if should_include:
                filtered_items.append(item)

        logger.info(
            "Batch filtering complete: %s included, %s filtered, %s skipped, %s errors",
            context.included_items,
            context.filtered_items,
            context.skipped_items,
            context.error_items
        )

        return filtered_items, context

    def filter_items_online_mode(
        self,
        items: List[Dict],
        where_config: Optional[Dict],
        conditional_clause: Optional[str] = None
    ) -> Tuple[List[Dict], WhereClauseFilteringContext]:
        """
        Filter items for online mode (bulk pre-filtering).

        Only applies 'filter' behavior at this stage. 'skip' behavior is handled
        downstream in the generator for streaming compatibility.

        Args:
            items: Data items to filter
            where_config: WHERE clause configuration dict
            conditional_clause: Optional conditional clause

        Returns:
            Tuple of (filtered_items, context):
            - filtered_items: Items to process (includes skip-behavior items)
            - context: WhereClauseFilteringContext with statistics

        Usage:
            handler = WhereClauseHandler(get_filter_service())
            filtered, context = handler.filter_items_online_mode(
                data, where_config
            )

            for item in filtered:
                process_item(item)  # Generator handles skip downstream
        """
        context = WhereClauseFilteringContext(total_items=len(items))
        config = self.validate_config(where_config)

        # No filtering configured
        if not self.should_evaluate_at_item_level(config):
            context.included_items = len(items)
            return items, context

        # Only apply 'filter' behavior here; 'skip' is downstream
        if config.behavior == FilterBehavior.SKIP:
            logger.info("Skip behavior detected - deferring to generator")
            context.included_items = len(items)
            return items, context

        # Delegate to FilterService for bulk filtering
        filtered_items, status_map = self.filter_service.apply_where_clause_filtering(
            items,
            config.to_dict(),
            conditional_clause
        )

        # Track results
        for target_id, status in status_map.items():
            context.track(target_id, status)

        logger.info(
            "Online filtering complete: %s included, %s filtered",
            context.included_items,
            context.filtered_items
        )

        return filtered_items, context

    def create_passthrough_item(
        self,
        original_item: Dict,
        filter_status: str,
        node_id: str,
        source_guid: str
    ) -> Dict:
        """
        Create passthrough item for skipped entries.

        Note: This is a convenience method. Consider using PassthroughItemBuilder
        for more comprehensive passthrough construction.

        Args:
            original_item: Original data item
            filter_status: Filter status ('skipped', 'filtered')
            node_id: Node identifier
            source_guid: Source GUID

        Returns:
            Passthrough item with metadata
        """
        processed_item = FieldManager().create_processed_item(
            source_guid=source_guid,
            content=original_item.get('content'),
            node_id=node_id
        )

        if 'metadata' not in processed_item:
            processed_item['metadata'] = {}

        processed_item['metadata'].update({
            'skipped_by_where_clause': True,
            'agent_type': 'passthrough',
            'reason': 'where_clause_not_matched',
            'filter_status': filter_status
        })

        return processed_item


# Convenience function for getting singleton instance
_GLOBAL_WHERE_CLAUSE_HANDLER = None


def get_where_clause_handler() -> WhereClauseHandler:
    """
    Get global WhereClauseHandler instance (convenience function).

    Returns:
        Singleton WhereClauseHandler instance
    """
    global _GLOBAL_WHERE_CLAUSE_HANDLER  # pylint: disable=global-statement
    if _GLOBAL_WHERE_CLAUSE_HANDLER is None:
        _GLOBAL_WHERE_CLAUSE_HANDLER = WhereClauseHandler(get_filter_service())
    return _GLOBAL_WHERE_CLAUSE_HANDLER
