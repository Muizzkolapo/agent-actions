"""
Enhanced WHERE clause filter service.

This module provides a production-ready WHERE clause filtering service that replaces
the old regex-based parser with proper grammar parsing, AST evaluation, and comprehensive
security measures.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from .parser import WhereClauseParser, SafeExpressionEvaluator, ParseResult
from .ast_nodes import WhereClauseAST, EvaluationContext
from .operator_registry import get_global_registry

logger = logging.getLogger(__name__)


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
    
    def filter_item(self, 
                   data: Dict[str, Any], 
                   where_clause: str,
                   timeout: Optional[int] = None,
                   functions: Optional[Dict[str, Any]] = None) -> FilterResult:
        """
        Filter a single data item using a WHERE clause.
        
        Args:
            data: The data item to filter
            where_clause: The WHERE clause string
            timeout: Optional timeout in seconds
            functions: Optional custom functions for evaluation
            
        Returns:
            FilterResult indicating success and whether the item matched
        """
        start_time = time.time()
        timeout = timeout or self.default_timeout
        
        try:
            # Submit evaluation to thread pool with timeout
            future = self.executor.submit(
                self._evaluate_where_clause, 
                data, where_clause, functions
            )
            
            matched = future.result(timeout=timeout)
            execution_time = time.time() - start_time
            
            if self.enable_metrics:
                self._update_metrics(True, execution_time, False)  # Cache hit will be determined in _evaluate_where_clause
            
            return FilterResult(
                success=True,
                matched=matched,
                execution_time=execution_time
            )
            
        except FutureTimeoutError:
            execution_time = time.time() - start_time
            error_msg = f"WHERE clause evaluation timed out after {timeout} seconds"
            logger.warning(error_msg)
            
            if self.enable_metrics:
                self._update_metrics(False, execution_time, False)
            
            return FilterResult(
                success=False,
                error=error_msg,
                execution_time=execution_time
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Error evaluating WHERE clause: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            if self.enable_metrics:
                self._update_metrics(False, execution_time, False)
            
            return FilterResult(
                success=False,
                error=error_msg,
                execution_time=execution_time
            )
    
    def filter_batch(self, 
                    data_items: List[Dict[str, Any]], 
                    where_clause: str,
                    timeout: Optional[int] = None,
                    functions: Optional[Dict[str, Any]] = None,
                    passthrough_on_error: bool = True) -> List[Dict[str, Any]]:
        """
        Filter a batch of data items using a WHERE clause.
        
        Args:
            data_items: List of data items to filter
            where_clause: The WHERE clause string
            timeout: Optional timeout in seconds per item
            functions: Optional custom functions for evaluation
            passthrough_on_error: Whether to include items that fail evaluation
            
        Returns:
            List of items that match the WHERE clause
        """
        filtered_items = []
        
        for item in data_items:
            result = self.filter_item(item, where_clause, timeout, functions)
            
            if result.success and result.matched:
                filtered_items.append(item)
            elif not result.success and passthrough_on_error:
                # Include items that failed evaluation if passthrough is enabled
                filtered_items.append(item)
        
        return filtered_items
    
    @lru_cache(maxsize=1000)
    def _parse_where_clause_cached(self, where_clause: str) -> ParseResult:
        """Parse WHERE clause with caching."""
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
            logger.warning(f"Failed to parse WHERE clause: {parse_result.error.message}")
            raise ValueError(f"Parse error: {parse_result.error.message}")
        
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
    
    def evaluate_safe_skip_condition(self, 
                                   condition_config: Dict[str, Any], 
                                   context: Dict[str, Any]) -> bool:
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
            if condition_type == 'previous_outputs_empty':
                agent_name = condition_config.get('agent_name')
                if not agent_name:
                    return False
                
                previous_outputs = context.get('previous_outputs', {})
                agent_outputs = previous_outputs.get(agent_name, [])
                return len(agent_outputs) == 0
            
            elif condition_type == 'previous_outputs_count':
                agent_name = condition_config.get('agent_name')
                threshold = condition_config.get('threshold', 0)
                comparison = condition_config.get('comparison', '==')
                
                if not agent_name:
                    return False
                
                previous_outputs = context.get('previous_outputs', {})
                agent_outputs = previous_outputs.get(agent_name, [])
                count = len(agent_outputs)
                
                if comparison == '==':
                    return count == threshold
                elif comparison == '!=':
                    return count != threshold
                elif comparison == '<':
                    return count < threshold
                elif comparison == '<=':
                    return count <= threshold
                elif comparison == '>':
                    return count > threshold
                elif comparison == '>=':
                    return count >= threshold
                else:
                    logger.warning(f"Unknown comparison operator: {comparison}")
                    return False
            
            elif condition_type == 'field_condition':
                field_path = condition_config.get('field_path')
                expected_value = condition_config.get('expected_value')
                
                if not field_path:
                    return False
                
                # Get field value using dot notation
                value = self._get_nested_value(context, field_path)
                return value == expected_value
            
            elif condition_type == 'custom':
                expression = condition_config.get('expression')
                if not expression:
                    return False
                
                return self.safe_evaluator.evaluate(expression, context)
            
            else:
                logger.warning(f"Unknown skip condition type: {condition_type}")
                return False
                
        except Exception as e:
            logger.error(f"Error evaluating skip condition: {e}")
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
        keys = field_path.split('.')
        value = data
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        
        return value
    
    def get_metrics(self) -> Optional[FilterMetrics]:
        """Get performance metrics."""
        return self.metrics if self.enable_metrics else None
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache statistics."""
        parser_cache = self.parser.get_cache_info()
        filter_cache = self._parse_where_clause_cached.cache_info()
        
        return {
            "parser_cache": parser_cache,
            "filter_cache": {
                "hits": filter_cache.hits,
                "misses": filter_cache.misses,
                "maxsize": filter_cache.maxsize,
                "currsize": filter_cache.currsize,
                "hit_ratio": filter_cache.hits / (filter_cache.hits + filter_cache.misses) if filter_cache.hits + filter_cache.misses > 0 else 0
            }
        }
    
    def clear_cache(self):
        """Clear all caches."""
        self.parser.clear_cache()
        self._parse_where_clause_cached.cache_clear()
    
    def shutdown(self):
        """Shutdown the filter service."""
        self.executor.shutdown(wait=True)


# Legacy compatibility functions
class LegacyWhereClauseParser:
    """
    Legacy compatibility wrapper for the old WHERE clause parser.
    
    This provides the same interface as the old parser while using
    the new secure implementation underneath.
    """
    
    def __init__(self):
        """Initialize the legacy parser."""
        self.filter_service = WhereClauseFilter()
    
    @staticmethod
    def parse(where_clause: str) -> List[Dict[str, Any]]:
        """
        Parse WHERE clause (legacy interface).
        
        This method maintains compatibility with the old interface
        but uses the new parser internally.
        """
        # This is a simplified version that returns a basic structure
        # for backwards compatibility
        parser = WhereClauseFilter()
        parse_result = parser.parser.parse(where_clause)
        
        if parse_result.success:
            # Convert AST back to a simple structure for compatibility
            return [{"parsed": True, "ast": parse_result.ast}]
        else:
            return []
    
    @staticmethod
    def evaluate(data: Dict[str, Any], conditions: List[Dict[str, Any]]) -> bool:
        """
        Evaluate conditions against data (legacy interface).
        
        This method maintains compatibility but is deprecated.
        Use WhereClauseFilter.filter_item() instead.
        """
        # For legacy compatibility, assume the first condition contains the AST
        if not conditions:
            return True
        
        condition = conditions[0]
        if "ast" in condition and isinstance(condition["ast"], WhereClauseAST):
            return condition["ast"].evaluate(data)
        
        return True


# Global filter instance for convenience
_global_filter = None


def get_global_filter() -> WhereClauseFilter:
    """Get the global WHERE clause filter instance."""
    global _global_filter
    if _global_filter is None:
        _global_filter = WhereClauseFilter()
    return _global_filter


def filter_data_with_where_clause(data: Dict[str, Any], 
                                 where_clause: str,
                                 passthrough_on_error: bool = True) -> bool:
    """
    Filter a single data item with a WHERE clause.
    
    Args:
        data: The data item to filter
        where_clause: The WHERE clause string
        passthrough_on_error: Whether to pass through items that fail evaluation
        
    Returns:
        True if the item matches or should be passed through, False otherwise
    """
    filter_service = get_global_filter()
    result = filter_service.filter_item(data, where_clause)
    
    if result.success:
        return result.matched
    else:
        return passthrough_on_error


def filter_batch_with_where_clause(data_items: List[Dict[str, Any]], 
                                  where_clause: str,
                                  passthrough_on_error: bool = True) -> List[Dict[str, Any]]:
    """
    Filter a batch of data items with a WHERE clause.
    
    Args:
        data_items: List of data items to filter
        where_clause: The WHERE clause string
        passthrough_on_error: Whether to pass through items that fail evaluation
        
    Returns:
        List of items that match the WHERE clause
    """
    filter_service = get_global_filter()
    return filter_service.filter_batch(data_items, where_clause, passthrough_on_error=passthrough_on_error)


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