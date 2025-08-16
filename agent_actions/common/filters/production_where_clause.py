"""
Production-hardened WHERE clause integration for agent workflows.
Combines all production features: security, monitoring, resilience, and performance.
"""
import time
import json
import hashlib
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass

from .secure_parser import (
    SecureWhereClauseParser, WhereCondition, SecurityContext,
    SecurityViolationError, InvalidWhereClauseError, WhereClauseTimeoutError,
    get_secure_parser
)
from ..monitoring.metrics import (
    record_where_clause_evaluation, record_where_clause_filter_result,
    record_where_clause_error
)
from ..monitoring.logging import (
    get_logger, log_where_clause_start, log_where_clause_success,
    log_where_clause_error, LoggingContext
)
from ..resilience.circuit_breaker import create_where_clause_circuit_breaker
from ..resilience.retry import where_clause_retry
from ..feature_flags.manager import (
    where_clause_enabled, where_clause_caching_enabled,
    where_clause_debug_enabled, where_clause_security_enabled,
    FeatureFlagContext
)
from ..correlation.tracker import (
    create_where_clause_correlation, where_clause_span,
    get_current_correlation, SpanContext
)
from ..performance.cache import (
    get_cached_where_clause_parse, cache_where_clause_parse,
    get_cached_where_clause_eval, cache_where_clause_eval
)


@dataclass
class WhereClauseConfig:
    """Enhanced WHERE clause configuration."""
    clause: str
    scope: str = "item"  # "item" or "agent"
    passthrough_on_empty: bool = True
    passthrough_on_error: bool = False
    max_evaluation_time_ms: float = 100.0
    enable_caching: bool = True
    security_level: str = "standard"  # "strict", "standard", "permissive"


class ProductionWhereClauseProcessor:
    """
    Production-hardened WHERE clause processor with comprehensive monitoring,
    security, resilience, and performance optimizations.
    """
    
    def __init__(self, agent_type: str, security_context: Optional[SecurityContext] = None):
        self.agent_type = agent_type
        self.security_context = security_context or SecurityContext(
            allowed_fields=set(),  # Empty means all allowed
            max_clause_length=1000,
            max_conditions=10,
            max_evaluation_time_ms=100.0
        )
        
        # Initialize components
        self.parser = get_secure_parser(self.security_context)
        self.structured_logger = get_logger()
        
        # Create circuit breaker for this agent type
        self.circuit_breaker = create_where_clause_circuit_breaker(
            agent_type=agent_type,
            scope="item",
            failure_threshold=3,
            recovery_timeout=30.0,
            timeout=1.0
        )
    
    def _create_data_hash(self, data: Dict[str, Any]) -> str:
        """Create a hash of the data for caching purposes."""
        try:
            # Create a deterministic hash of the data
            data_str = json.dumps(data, sort_keys=True, default=str)
            return hashlib.md5(data_str.encode()).hexdigest()
        except Exception:
            # Fallback if data is not JSON serializable
            return hashlib.md5(str(data).encode()).hexdigest()
    
    def _should_use_cache(self, config: WhereClauseConfig) -> bool:
        """Determine if caching should be used."""
        return (
            config.enable_caching and 
            where_clause_caching_enabled(self.agent_type)
        )
    
    @where_clause_span("parse_where_clause")
    def parse_where_clause(self, config: WhereClauseConfig) -> List[WhereCondition]:
        """
        Parse WHERE clause with full production features.
        
        Args:
            config: WHERE clause configuration
            
        Returns:
            List of parsed conditions
            
        Raises:
            SecurityViolationError: For security violations
            InvalidWhereClauseError: For invalid syntax
        """
        if not where_clause_enabled(self.agent_type):
            raise InvalidWhereClauseError("WHERE clause functionality is disabled")
        
        # Check cache first
        if self._should_use_cache(config):
            cached_result = get_cached_where_clause_parse(config.clause)
            if cached_result is not None:
                return cached_result
        
        # Parse with circuit breaker protection
        try:
            conditions = self.circuit_breaker.call(
                self.parser.parse,
                config.clause,
                self.agent_type
            )
            
            # Cache the result
            if self._should_use_cache(config):
                cache_where_clause_parse(config.clause, conditions, ttl=300)
            
            return conditions
        
        except Exception as e:
            record_where_clause_error(type(e).__name__, self.agent_type, "parse")
            raise
    
    @where_clause_span("evaluate_where_clause")
    def evaluate_conditions(
        self,
        data: Dict[str, Any],
        conditions: List[WhereCondition],
        config: WhereClauseConfig
    ) -> bool:
        """
        Evaluate WHERE clause conditions against data.
        
        Args:
            data: Data to evaluate against
            conditions: Parsed conditions
            config: WHERE clause configuration
            
        Returns:
            True if all conditions match, False otherwise
        """
        if not conditions:
            return True
        
        start_time = time.time()
        data_hash = self._create_data_hash(data)
        
        # Check cache first
        if self._should_use_cache(config):
            cached_result = get_cached_where_clause_eval(
                config.clause, data_hash
            )
            if cached_result is not None:
                return cached_result
        
        try:
            # Evaluate with circuit breaker protection
            result = self.circuit_breaker.call(
                self.parser.evaluate,
                data,
                conditions,
                self.agent_type
            )
            
            # Cache the result (shorter TTL for eval cache)
            if self._should_use_cache(config):
                cache_where_clause_eval(config.clause, data_hash, result, ttl=60)
            
            # Record metrics
            evaluation_time = (time.time() - start_time) * 1000
            record_where_clause_evaluation(
                "item", self.agent_type, "success", evaluation_time
            )
            
            # Record filter result
            record_where_clause_filter_result(
                self.agent_type,
                "passed" if result else "filtered",
                1
            )
            
            return result
        
        except Exception as e:
            evaluation_time = (time.time() - start_time) * 1000
            record_where_clause_error(type(e).__name__, self.agent_type, "evaluation")
            
            # Handle error based on configuration
            if config.passthrough_on_error:
                self.structured_logger.warning(
                    f"WHERE clause evaluation failed, using passthrough: {e}",
                    context={'component': 'where_clause', 'operation': 'error_passthrough'},
                    error_details={
                        'agent_type': self.agent_type,
                        'clause': config.clause,
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    }
                )
                return True
            else:
                raise
    
    def should_process_item(
        self,
        item_data: Dict[str, Any],
        config: WhereClauseConfig,
        correlation_id: Optional[str] = None
    ) -> bool:
        """
        Determine if an item should be processed based on WHERE clause.
        
        Args:
            item_data: Item data to evaluate
            config: WHERE clause configuration
            correlation_id: Optional correlation ID for tracking
            
        Returns:
            True if item should be processed, False otherwise
        """
        # Create correlation context if needed
        correlation = None
        if correlation_id:
            correlation = create_where_clause_correlation(
                agent_type=self.agent_type,
                where_clause=config.clause,
                scope=config.scope,
                workflow_id=correlation_id
            )
        
        with LoggingContext(
            correlation_id=correlation_id,
            agent_type=self.agent_type
        ):
            try:
                # Log start of evaluation
                if where_clause_debug_enabled(self.agent_type):
                    log_where_clause_start(
                        config.clause, config.scope, 1, 1
                    )
                
                # Parse conditions
                conditions = self.parse_where_clause(config)
                
                if not conditions:
                    # No conditions means process all items
                    return True
                
                # Evaluate conditions
                result = self.evaluate_conditions(item_data, conditions, config)
                
                # Log success
                if where_clause_debug_enabled(self.agent_type):
                    log_where_clause_success(
                        config.clause, config.scope, 0, len(conditions), 1, 1
                    )
                
                return result
            
            except (SecurityViolationError, InvalidWhereClauseError) as e:
                # Security and syntax errors should not be retried
                log_where_clause_error(
                    config.clause, config.scope, 0, len(conditions) if 'conditions' in locals() else 0,
                    e, {'agent_type': self.agent_type, 'item_keys': list(item_data.keys())}
                )
                
                if config.passthrough_on_error:
                    return True
                else:
                    raise
            
            except Exception as e:
                # Other errors might be transient
                log_where_clause_error(
                    config.clause, config.scope, 0, len(conditions) if 'conditions' in locals() else 0,
                    e, {'agent_type': self.agent_type, 'item_keys': list(item_data.keys())}
                )
                
                if config.passthrough_on_error:
                    return True
                else:
                    raise
    
    def filter_batch(
        self,
        batch_data: List[Dict[str, Any]],
        config: WhereClauseConfig,
        correlation_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Filter a batch of items based on WHERE clause.
        
        Args:
            batch_data: List of items to filter
            config: WHERE clause configuration
            correlation_id: Optional correlation ID for tracking
            
        Returns:
            Filtered list of items
        """
        if not batch_data:
            return []
        
        start_time = time.time()
        
        with LoggingContext(
            correlation_id=correlation_id,
            agent_type=self.agent_type
        ):
            try:
                # Parse conditions once for the batch
                conditions = self.parse_where_clause(config)
                
                if not conditions:
                    # No conditions means process all items
                    return batch_data
                
                # Filter items
                filtered_items = []
                for item in batch_data:
                    try:
                        if self.evaluate_conditions(item, conditions, config):
                            filtered_items.append(item)
                    except Exception as e:
                        if config.passthrough_on_error:
                            filtered_items.append(item)
                        else:
                            # Re-raise for batch processing failure
                            raise
                
                # Log batch processing results
                processing_time = (time.time() - start_time) * 1000
                filtered_count = len(filtered_items)
                total_count = len(batch_data)
                
                self.structured_logger.info(
                    f"Batch WHERE clause filtering completed",
                    context={'component': 'where_clause', 'operation': 'batch_filter'},
                    performance_metrics={
                        'agent_type': self.agent_type,
                        'total_items': total_count,
                        'filtered_items': filtered_count,
                        'pass_rate': filtered_count / total_count if total_count > 0 else 0,
                        'processing_time_ms': processing_time,
                        'items_per_second': total_count / (processing_time / 1000) if processing_time > 0 else 0
                    }
                )
                
                # Record batch metrics
                record_where_clause_filter_result(
                    self.agent_type, "batch_passed", filtered_count
                )
                record_where_clause_filter_result(
                    self.agent_type, "batch_filtered", total_count - filtered_count
                )
                
                return filtered_items
            
            except Exception as e:
                processing_time = (time.time() - start_time) * 1000
                
                log_where_clause_error(
                    config.clause, "batch", processing_time, 
                    len(conditions) if 'conditions' in locals() else 0,
                    e, {
                        'agent_type': self.agent_type,
                        'batch_size': len(batch_data)
                    }
                )
                
                if config.passthrough_on_error:
                    return batch_data
                else:
                    raise
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics for this processor."""
        return {
            'agent_type': self.agent_type,
            'circuit_breaker': self.circuit_breaker.get_stats(),
            'parser_cache': self.parser.get_cache_stats(),
            'security_context': {
                'max_clause_length': self.security_context.max_clause_length,
                'max_conditions': self.security_context.max_conditions,
                'max_evaluation_time_ms': self.security_context.max_evaluation_time_ms,
                'allowed_fields_count': len(self.security_context.allowed_fields)
            }
        }


# Factory function for creating processors
def create_where_clause_processor(
    agent_type: str,
    allowed_fields: Optional[set] = None,
    security_level: str = "standard"
) -> ProductionWhereClauseProcessor:
    """
    Factory function to create a WHERE clause processor with appropriate security settings.
    
    Args:
        agent_type: Type of agent this processor is for
        allowed_fields: Set of allowed field names (None means all allowed)
        security_level: Security level ("strict", "standard", "permissive")
        
    Returns:
        Configured ProductionWhereClauseProcessor
    """
    # Configure security context based on level
    if security_level == "strict":
        security_context = SecurityContext(
            allowed_fields=allowed_fields or set(),
            max_clause_length=500,
            max_conditions=5,
            max_evaluation_time_ms=50.0,
            allow_nested_fields=False,
            max_nesting_depth=2
        )
    elif security_level == "permissive":
        security_context = SecurityContext(
            allowed_fields=allowed_fields or set(),
            max_clause_length=2000,
            max_conditions=20,
            max_evaluation_time_ms=200.0,
            allow_nested_fields=True,
            max_nesting_depth=10
        )
    else:  # standard
        security_context = SecurityContext(
            allowed_fields=allowed_fields or set(),
            max_clause_length=1000,
            max_conditions=10,
            max_evaluation_time_ms=100.0,
            allow_nested_fields=True,
            max_nesting_depth=5
        )
    
    return ProductionWhereClauseProcessor(agent_type, security_context)


# Convenience functions for common use cases
def filter_item_with_where_clause(
    item_data: Dict[str, Any],
    where_clause: str,
    agent_type: str,
    **kwargs
) -> bool:
    """
    Convenience function to filter a single item with a WHERE clause.
    
    Args:
        item_data: Item data to evaluate
        where_clause: WHERE clause string
        agent_type: Agent type for context
        **kwargs: Additional configuration options
        
    Returns:
        True if item should be processed, False otherwise
    """
    config = WhereClauseConfig(clause=where_clause, **kwargs)
    processor = create_where_clause_processor(agent_type)
    return processor.should_process_item(item_data, config)


def filter_batch_with_where_clause(
    batch_data: List[Dict[str, Any]],
    where_clause: str,
    agent_type: str,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    Convenience function to filter a batch of items with a WHERE clause.
    
    Args:
        batch_data: List of items to filter
        where_clause: WHERE clause string
        agent_type: Agent type for context
        **kwargs: Additional configuration options
        
    Returns:
        Filtered list of items
    """
    config = WhereClauseConfig(clause=where_clause, **kwargs)
    processor = create_where_clause_processor(agent_type)
    return processor.filter_batch(batch_data, config)