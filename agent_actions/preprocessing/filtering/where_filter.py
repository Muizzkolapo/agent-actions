"""
Enhanced WHERE clause filter service.

This module provides a production-ready WHERE clause filtering service that replaces
the old regex-based parser with proper grammar parsing, AST evaluation, and comprehensive
security measures.
"""

import logging
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from agent_actions.utilities.dict_utils import get_nested_value
from ..parsing.parser import WhereClauseParser, SafeExpressionEvaluator, ParseResult

logger = logging.getLogger(__name__)


def _get_lru_cache_info(cached_func):
    """Get cache_info from an lru_cache-decorated function."""
    return cached_func.cache_info()


@dataclass
class FilterResult:
    """Result of filtering operation."""
    success: bool
    matched: bool = False
    error: Optional[str] = None
    execution_time: float = 0.0
    cache_hit: bool = False


@dataclass
class FilterMetrics:
    """Metrics for filter operations."""
    total_evaluations: int = 0
    successful_evaluations: int = 0
    failed_evaluations: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    average_execution_time: float = 0.0
    total_execution_time: float = 0.0


@dataclass
class FilterItemRequest:
    """Request parameters for filtering a single item."""
    data: Dict[str, Any]
    where_clause: str
    timeout: Optional[int] = None
    functions: Optional[Dict[str, Any]] = None


@dataclass
class FilterBatchRequest:
    """Request parameters for filtering a batch of items."""
    data_items: List[Dict[str, Any]]
    where_clause: str
    timeout: Optional[int] = None
    functions: Optional[Dict[str, Any]] = None
    passthrough_on_error: bool = True


class WhereClauseFilter:
    """
    Enhanced WHERE clause filter with security, performance, and reliability improvements.

    Features:
    - AST-based evaluation instead of eval()
    - Comprehensive input validation
    - LRU caching for performance
    - Timeout protection
    - Detailed metrics collection
    - Thread-safe operations
    """

    def __init__(self,
                 cache_size: int = 1000,
                 default_timeout: int = 5,
                 enable_metrics: bool = True):
        """
        Initialize the WHERE clause filter.

        Args:
            cache_size: Size of the LRU cache for parsed expressions
            default_timeout: Default timeout for evaluations in seconds
            enable_metrics: Whether to collect performance metrics
        """
        self.parser = WhereClauseParser()
        self.safe_evaluator = SafeExpressionEvaluator()
        self.cache_size = cache_size
        self.default_timeout = default_timeout
        self.enable_metrics = enable_metrics

        if enable_metrics:
            self.metrics = FilterMetrics()

        # Thread pool for timeout protection
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="where_filter")

    def filter_item(self, request: FilterItemRequest) -> FilterResult:
        """
        Filter a single data item using a WHERE clause.

        Args:
            request: FilterItemRequest containing all parameters

        Returns:
            FilterResult indicating success and whether the item matched
        """
        start_time = time.time()
        timeout = request.timeout or self.default_timeout

        try:
            # Submit evaluation to thread pool with timeout
            future = self.executor.submit(
                self._evaluate_where_clause,
                request.data, request.where_clause, request.functions
            )

            matched = future.result(timeout=timeout)
            execution_time = time.time() - start_time

            if self.enable_metrics:
                # Cache hit will be determined in _evaluate_where_clause
                self._update_metrics(True, execution_time, False)

            return FilterResult(
                success=True,
                matched=matched,
                execution_time=execution_time
            )

        except FutureTimeoutError:
            execution_time = time.time() - start_time
            error_msg = (
                f"WHERE clause evaluation timed out after {timeout} seconds"
            )
            logger.warning(error_msg)

            if self.enable_metrics:
                self._update_metrics(False, execution_time, False)

            return FilterResult(
                success=False,
                error=error_msg,
                execution_time=execution_time
            )

        except ValueError as e:
            execution_time = time.time() - start_time
            error_msg = f"Error evaluating WHERE clause: {str(e)}"
            logger.debug(error_msg, exc_info=True)

            if self.enable_metrics:
                self._update_metrics(False, execution_time, False)

            return FilterResult(
                success=False,
                error=error_msg,
                execution_time=execution_time
            )

    def filter_batch(self, request: FilterBatchRequest) -> List[Dict[str, Any]]:
        """
        Filter a batch of data items using a WHERE clause.

        Args:
            request: FilterBatchRequest containing all parameters

        Returns:
            List of items that match the WHERE clause
        """
        filtered_items = []

        for item in request.data_items:
            item_request = FilterItemRequest(
                data=item,
                where_clause=request.where_clause,
                timeout=request.timeout,
                functions=request.functions
            )
            result = self.filter_item(item_request)

            if result.success and result.matched:
                filtered_items.append(item)
            elif not result.success and request.passthrough_on_error:
                # Include items that failed evaluation if passthrough is enabled
                filtered_items.append(item)

        return filtered_items

    def _parse_where_clause_cached(self, where_clause: str) -> ParseResult:
        """Parse WHERE clause with caching."""
        return self._cached_parse(where_clause)

    @lru_cache(maxsize=1000)
    def _cached_parse(self, where_clause: str) -> ParseResult:
        """Internal cached parse method."""
        return self.parser.parse(where_clause)

    def _evaluate_where_clause(self,
                              data: Dict[str, Any],
                              where_clause: str,
                              functions: Optional[Dict[str, Any]]) -> bool:
        """
        Internal method to evaluate a WHERE clause against data.

        Args:
            data: The data to evaluate against
            where_clause: The WHERE clause string
            functions: Optional custom functions

        Returns:
            True if the data matches the WHERE clause, False otherwise
        """
        # Parse the WHERE clause (with caching)
        parse_result = self._parse_where_clause_cached(where_clause)

        if not parse_result.success:
            error_msg = parse_result.error.message
            logger.warning("Failed to parse WHERE clause: %s", error_msg)
            raise ValueError(f"Parse error: {error_msg}")

        # Evaluate the AST
        return parse_result.ast.evaluate(data, functions)

    def _update_metrics(self, success: bool, execution_time: float, cache_hit: bool):
        """Update performance metrics."""
        if not self.enable_metrics:
            return

        self.metrics.total_evaluations += 1
        self.metrics.total_execution_time += execution_time

        if success:
            self.metrics.successful_evaluations += 1
        else:
            self.metrics.failed_evaluations += 1

        if cache_hit:
            self.metrics.cache_hits += 1
        else:
            self.metrics.cache_misses += 1

        # Update average
        self.metrics.average_execution_time = (
            self.metrics.total_execution_time / self.metrics.total_evaluations
        )

    def _evaluate_previous_outputs_empty(
        self, condition_config: Dict[str, Any], context: Dict[str, Any]
    ) -> bool:
        """Evaluate 'previous_outputs_empty' condition."""
        agent_name = condition_config.get('agent_name')
        if not agent_name:
            return False

        previous_outputs = context.get('previous_outputs', {})
        agent_outputs = previous_outputs.get(agent_name, [])
        return len(agent_outputs) == 0

    def _evaluate_previous_outputs_count(
        self, condition_config: Dict[str, Any], context: Dict[str, Any]
    ) -> bool:
        """Evaluate 'previous_outputs_count' condition."""
        agent_name = condition_config.get('agent_name')
        threshold = condition_config.get('threshold', 0)
        comparison = condition_config.get('comparison', '==')

        if not agent_name:
            return False

        previous_outputs = context.get('previous_outputs', {})
        agent_outputs = previous_outputs.get(agent_name, [])
        count = len(agent_outputs)

        comparisons = {
            '==': count == threshold,
            '!=': count != threshold,
            '<': count < threshold,
            '<=': count <= threshold,
            '>': count > threshold,
            '>=': count >= threshold
        }

        if comparison in comparisons:
            return comparisons[comparison]

        logger.warning("Unknown comparison operator: %s", comparison)
        return False

    def _evaluate_field_condition(
        self, condition_config: Dict[str, Any], context: Dict[str, Any]
    ) -> bool:
        """Evaluate 'field_condition' type."""
        field_path = condition_config.get('field_path')
        expected_value = condition_config.get('expected_value')

        if not field_path:
            return False

        value = self._get_nested_value(context, field_path)
        return value == expected_value

    def _evaluate_custom_condition(
        self, condition_config: Dict[str, Any], context: Dict[str, Any]
    ) -> bool:
        """Evaluate 'custom' condition type."""
        expression = condition_config.get('expression')
        if not expression:
            return False

        return self.safe_evaluator.evaluate(expression, context)

    def evaluate_safe_skip_condition(
        self, condition_config: Dict[str, Any], context: Dict[str, Any]
    ) -> bool:
        """
        Safely evaluate a skip condition without using eval().

        Args:
            condition_config: Skip condition configuration
            context: Evaluation context (e.g., previous_outputs)

        Returns:
            True if the agent should be skipped, False otherwise
        """
        condition_type = condition_config.get('condition_type')

        try:
            condition_handlers = {
                'previous_outputs_empty': self._evaluate_previous_outputs_empty,
                'previous_outputs_count': self._evaluate_previous_outputs_count,
                'field_condition': self._evaluate_field_condition,
                'custom': self._evaluate_custom_condition
            }

            handler = condition_handlers.get(condition_type)
            if handler:
                return handler(condition_config, context)

            logger.warning("Unknown skip condition type: %s", condition_type)
            return False

        except ValueError as e:
            logger.error("Error evaluating skip condition: %s", e)
            return False

    def _get_nested_value(self, data: Dict[str, Any], field_path: str) -> Any:
        """
        Get a nested value from a dictionary using dot notation.

        Args:
            data: The data dictionary
            field_path: The field path (e.g., 'user.profile.name')

        Returns:
            The field value or None if not found
        """
        return get_nested_value(data, field_path)

    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache statistics."""
        parser_cache = self.parser.get_cache_info()
        filter_cache = _get_lru_cache_info(type(self)._cached_parse)

        total_calls = filter_cache.hits + filter_cache.misses
        hit_ratio = filter_cache.hits / total_calls if total_calls > 0 else 0

        return {
            "parser_cache": parser_cache,
            "filter_cache": {
                "hits": filter_cache.hits,
                "misses": filter_cache.misses,
                "maxsize": filter_cache.maxsize,
                "currsize": filter_cache.currsize,
                "hit_ratio": hit_ratio
            }
        }

    def clear_cache(self):
        """Clear all caches."""
        self.parser.clear_cache()
        self._cached_parse.cache_clear()

    def shutdown(self):
        """Shutdown the filter service."""
        self.executor.shutdown(wait=True)


# Global filter instance for convenience
_GLOBAL_FILTER = None


def get_global_filter() -> WhereClauseFilter:
    """Get the global WHERE clause filter instance."""
    global _GLOBAL_FILTER  # pylint: disable=global-statement
    if _GLOBAL_FILTER is None:
        _GLOBAL_FILTER = WhereClauseFilter()
    return _GLOBAL_FILTER


def evaluate_safe_skip_condition(condition_config: Dict[str, Any],
                                context: Dict[str, Any]) -> bool:
    """
    Safely evaluate a skip condition.

    Args:
        condition_config: Skip condition configuration
        context: Evaluation context

    Returns:
        True if the condition indicates the agent should be skipped
    """
    filter_service = get_global_filter()
    return filter_service.evaluate_safe_skip_condition(condition_config, context)
