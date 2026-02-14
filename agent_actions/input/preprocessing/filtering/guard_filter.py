"""
Guard filter service.
"""

import logging
import time
from typing import Any, Dict, Optional
from dataclasses import dataclass
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from agent_actions.logging import fire_event
from agent_actions.logging.events.types import (
    GuardEvaluationTimeoutEvent,
    GuardEvaluationErrorEvent,
)
from ..parsing.parser import WhereClauseParser, ParseResult

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
    condition: str
    timeout: Optional[int] = None
    functions: Optional[Dict[str, Any]] = None


class GuardFilter:
    """
    Guard filter with security, performance, and reliability improvements.

    Features:
    - AST-based evaluation instead of eval()
    - Comprehensive input validation
    - LRU caching for performance
    - Timeout protection
    - Detailed metrics collection
    - Thread-safe operations
    """

    def __init__(
        self, cache_size: int = 1000, default_timeout: int = 5, enable_metrics: bool = True
    ):
        """
        Initialize the guard filter.

        Args:
            cache_size: Size of the LRU cache for parsed expressions
            default_timeout: Default timeout for evaluations in seconds
            enable_metrics: Whether to collect performance metrics
        """
        self.parser = WhereClauseParser()
        self.cache_size = cache_size
        self.default_timeout = default_timeout
        self.enable_metrics = enable_metrics

        if enable_metrics:
            self.metrics = FilterMetrics()

        # Thread pool for timeout protection
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="guard_filter")

    def filter_item(self, request: FilterItemRequest) -> FilterResult:
        """
        Filter a single data item using a guard condition.

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
                self._evaluate_guard_condition, request.data, request.condition, request.functions
            )

            matched = future.result(timeout=timeout)
            execution_time = time.time() - start_time

            if self.enable_metrics:
                # Cache hit will be determined in _evaluate_where_clause
                self._update_metrics(True, execution_time, False)

            return FilterResult(success=True, matched=matched, execution_time=execution_time)

        except FutureTimeoutError:
            execution_time = time.time() - start_time
            error_msg = f"Guard condition evaluation timed out after {timeout} seconds"
            logger.warning(error_msg)

            fire_event(
                GuardEvaluationTimeoutEvent(
                    guard_clause=request.condition,
                    timeout_seconds=timeout,
                )
            )

            if self.enable_metrics:
                self._update_metrics(False, execution_time, False)

            return FilterResult(success=False, error=error_msg, execution_time=execution_time)

        except ValueError as e:
            execution_time = time.time() - start_time
            error_msg = f"Error evaluating guard condition: {str(e)}"
            logger.warning(error_msg, exc_info=True)

            fire_event(
                GuardEvaluationErrorEvent(
                    guard_clause=request.condition,
                    error=str(e),
                )
            )

            if self.enable_metrics:
                self._update_metrics(False, execution_time, False)

            return FilterResult(success=False, error=error_msg, execution_time=execution_time)

    def _parse_condition_cached(self, condition: str) -> ParseResult:
        """Parse guard condition with caching."""
        return self._cached_parse(condition)

    @lru_cache(maxsize=1000)
    def _cached_parse(self, condition: str) -> ParseResult:
        """Internal cached parse method."""
        return self.parser.parse(condition)

    def _evaluate_guard_condition(
        self, data: Dict[str, Any], condition: str, functions: Optional[Dict[str, Any]]
    ) -> bool:
        """
        Internal method to evaluate a guard condition against data.

        Args:
            data: The data to evaluate against
            condition: The guard condition string
            functions: Optional custom functions

        Returns:
            True if the data matches the guard condition, False otherwise
        """
        # Parse the guard condition (with caching)
        parse_result = self._parse_condition_cached(condition)

        if not parse_result.success:
            error_msg = parse_result.error.message
            logger.warning("Failed to parse guard condition: %s", error_msg)
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
                "hit_ratio": hit_ratio,
            },
        }

    def clear_cache(self):
        """Clear all caches."""
        self.parser.clear_cache()
        self._cached_parse.cache_clear()

    def shutdown(self):
        """Shutdown the filter service."""
        self.executor.shutdown(wait=True)


# Global guard filter instance for convenience
_GLOBAL_GUARD_FILTER = None


def get_global_guard_filter() -> GuardFilter:
    """Get the global guard filter instance."""
    global _GLOBAL_GUARD_FILTER
    if _GLOBAL_GUARD_FILTER is None:
        _GLOBAL_GUARD_FILTER = GuardFilter()
    return _GLOBAL_GUARD_FILTER
