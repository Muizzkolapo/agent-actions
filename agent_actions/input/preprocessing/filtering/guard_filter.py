"""Guard filter service with AST-based evaluation, caching, and timeout protection."""

import atexit
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.validation_events import (
    GuardEvaluationErrorEvent,
    GuardEvaluationTimeoutEvent,
)

from ..parsing.parser import ParseResult, WhereClauseParser

logger = logging.getLogger(__name__)


def _get_lru_cache_info(cached_func):
    """Get cache_info from an lru_cache-decorated function."""
    return cached_func.cache_info()


@dataclass
class FilterResult:
    """Result of filtering operation."""

    success: bool
    matched: bool = False
    error: str | None = None
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

    data: dict[str, Any]
    condition: str
    timeout: int | None = None
    functions: dict[str, Any] | None = None


class GuardFilter:
    """Thread-safe guard filter with AST-based evaluation, caching, and timeout protection."""

    def __init__(
        self, cache_size: int = 1000, default_timeout: int = 5, enable_metrics: bool = True
    ):
        self.parser = WhereClauseParser()
        self.cache_size = cache_size
        self.default_timeout = default_timeout
        self.enable_metrics = enable_metrics

        if enable_metrics:
            self.metrics = FilterMetrics()

        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="guard_filter")

    def filter_item(self, request: FilterItemRequest) -> FilterResult:
        """Filter a single data item using a guard condition."""
        start_time = time.time()
        timeout = request.timeout or self.default_timeout

        try:
            future = self.executor.submit(
                self._evaluate_guard_condition, request.data, request.condition, request.functions
            )

            matched = future.result(timeout=timeout)
            execution_time = time.time() - start_time

            if self.enable_metrics:
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

    @lru_cache(maxsize=1000)  # noqa: B019
    def _cached_parse(self, condition: str) -> ParseResult:
        """Internal cached parse method."""
        return self.parser.parse(condition)

    def _evaluate_guard_condition(
        self, data: dict[str, Any], condition: str, functions: dict[str, Any] | None
    ) -> bool:
        """Evaluate a guard condition against data."""
        parse_result = self._parse_condition_cached(condition)

        if not parse_result.success:
            if parse_result.error is None:
                raise RuntimeError(
                    "ParseResult indicates failure but error is None; "
                    "expected a ParseError with details"
                )
            error_msg = parse_result.error.message
            logger.warning("Failed to parse guard condition: %s", error_msg)
            raise ValueError(f"Parse error: {error_msg}")

        if parse_result.ast is None:
            raise RuntimeError(
                "ParseResult indicates success but ast is None; expected a WhereClauseAST node"
            )
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

        self.metrics.average_execution_time = (
            self.metrics.total_execution_time / self.metrics.total_evaluations
        )

    def get_cache_info(self) -> dict[str, Any]:
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


# Per-process singleton; assumes one workflow per process.
# Cleaned up via atexit. Use reset_global_guard_filter() in tests.
_GLOBAL_GUARD_FILTER: GuardFilter | None = None
_GUARD_FILTER_LOCK = threading.Lock()


def get_global_guard_filter() -> GuardFilter:
    """Get the global guard filter instance (thread-safe)."""
    global _GLOBAL_GUARD_FILTER
    if _GLOBAL_GUARD_FILTER is None:
        with _GUARD_FILTER_LOCK:
            if _GLOBAL_GUARD_FILTER is None:
                _GLOBAL_GUARD_FILTER = GuardFilter()
                atexit.register(_GLOBAL_GUARD_FILTER.shutdown)
    return _GLOBAL_GUARD_FILTER


def reset_global_guard_filter() -> None:
    """Reset the global guard filter instance (for testing).

    Shuts down the existing instance's ThreadPoolExecutor and unregisters
    its atexit handler before clearing.  Must be called from a single
    thread (e.g. a serial test fixture), not concurrently with
    ``get_global_guard_filter()``.
    """
    global _GLOBAL_GUARD_FILTER
    with _GUARD_FILTER_LOCK:
        if _GLOBAL_GUARD_FILTER is not None:
            atexit.unregister(_GLOBAL_GUARD_FILTER.shutdown)
            _GLOBAL_GUARD_FILTER.shutdown()
            _GLOBAL_GUARD_FILTER = None
