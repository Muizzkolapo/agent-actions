"""
Production-grade request correlation and debugging system.
Provides distributed tracing and correlation ID tracking across the pipeline.
"""
import uuid
import time
import threading
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from contextvars import ContextVar
from datetime import datetime
import json
import logging

from ..monitoring.metrics import get_metrics_collector, set_request_correlation
from ..monitoring.logging import get_logger, LoggingContext

logger = logging.getLogger(__name__)

# Context variables for request correlation
request_correlation_var: ContextVar[Optional['RequestCorrelation']] = ContextVar('request_correlation', default=None)


@dataclass
class TraceSpan:
    """Represents a single span in a distributed trace."""
    span_id: str
    operation_name: str
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    tags: Dict[str, Any] = field(default_factory=dict)
    logs: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    parent_span_id: Optional[str] = None
    
    def finish(self):
        """Finish the span and calculate duration."""
        if self.end_time is None:
            self.end_time = time.time()
            self.duration_ms = (self.end_time - self.start_time) * 1000
    
    def add_tag(self, key: str, value: Any):
        """Add a tag to the span."""
        self.tags[key] = value
    
    def add_log(self, message: str, level: str = "info", **kwargs):
        """Add a log entry to the span."""
        log_entry = {
            'timestamp': time.time(),
            'message': message,
            'level': level,
            **kwargs
        }
        self.logs.append(log_entry)
    
    def set_error(self, error: Exception):
        """Mark the span as having an error."""
        self.error = f"{type(error).__name__}: {str(error)}"
        self.add_tag("error", True)
        self.add_tag("error_type", type(error).__name__)
        self.add_tag("error_message", str(error))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert span to dictionary for serialization."""
        return {
            'span_id': self.span_id,
            'operation_name': self.operation_name,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration_ms': self.duration_ms,
            'tags': self.tags,
            'logs': self.logs,
            'error': self.error,
            'parent_span_id': self.parent_span_id
        }


@dataclass
class RequestCorrelation:
    """Represents request correlation and tracing information."""
    correlation_id: str
    trace_id: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    agent_type: Optional[str] = None
    workflow_id: Optional[str] = None
    request_start_time: float = field(default_factory=time.time)
    spans: Dict[str, TraceSpan] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def create_span(
        self,
        operation_name: str,
        parent_span_id: Optional[str] = None,
        **tags
    ) -> TraceSpan:
        """Create a new span for this request."""
        span_id = str(uuid.uuid4())
        span = TraceSpan(
            span_id=span_id,
            operation_name=operation_name,
            start_time=time.time(),
            parent_span_id=parent_span_id,
            tags=tags
        )
        
        # Add common tags
        span.add_tag("correlation_id", self.correlation_id)
        span.add_tag("trace_id", self.trace_id)
        if self.user_id:
            span.add_tag("user_id", self.user_id)
        if self.agent_type:
            span.add_tag("agent_type", self.agent_type)
        if self.workflow_id:
            span.add_tag("workflow_id", self.workflow_id)
        
        self.spans[span_id] = span
        return span
    
    def get_span(self, span_id: str) -> Optional[TraceSpan]:
        """Get a span by ID."""
        return self.spans.get(span_id)
    
    def finish_span(self, span_id: str):
        """Finish a span."""
        span = self.spans.get(span_id)
        if span:
            span.finish()
    
    def add_metadata(self, key: str, value: Any):
        """Add metadata to the request correlation."""
        self.metadata[key] = value
    
    def get_active_spans(self) -> List[TraceSpan]:
        """Get all active (unfinished) spans."""
        return [span for span in self.spans.values() if span.end_time is None]
    
    def get_duration_ms(self) -> float:
        """Get total request duration in milliseconds."""
        return (time.time() - self.request_start_time) * 1000
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'correlation_id': self.correlation_id,
            'trace_id': self.trace_id,
            'user_id': self.user_id,
            'session_id': self.session_id,
            'agent_type': self.agent_type,
            'workflow_id': self.workflow_id,
            'request_start_time': self.request_start_time,
            'request_duration_ms': self.get_duration_ms(),
            'spans': {span_id: span.to_dict() for span_id, span in self.spans.items()},
            'metadata': self.metadata
        }


class CorrelationTracker:
    """
    Production-grade correlation tracker with distributed tracing support.
    """
    
    def __init__(self):
        self._correlations: Dict[str, RequestCorrelation] = {}
        self._lock = threading.RLock()
        self.metrics = get_metrics_collector()
        self.structured_logger = get_logger()
        
        # Cleanup thread for old correlations
        self._cleanup_thread = threading.Thread(target=self._cleanup_old_correlations, daemon=True)
        self._cleanup_thread.start()
    
    def create_correlation(
        self,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_type: Optional[str] = None,
        workflow_id: Optional[str] = None,
        **metadata
    ) -> RequestCorrelation:
        """Create a new request correlation."""
        correlation_id = correlation_id or str(uuid.uuid4())
        trace_id = trace_id or str(uuid.uuid4())
        
        correlation = RequestCorrelation(
            correlation_id=correlation_id,
            trace_id=trace_id,
            user_id=user_id,
            session_id=session_id,
            agent_type=agent_type,
            workflow_id=workflow_id,
            metadata=metadata
        )
        
        with self._lock:
            self._correlations[correlation_id] = correlation
        
        # Set metrics
        set_request_correlation(correlation_id, agent_type or "unknown", {
            'trace_id': trace_id,
            'user_id': user_id or 'anonymous',
            'workflow_id': workflow_id or 'unknown'
        })
        
        # Log correlation creation
        self.structured_logger.info(
            f"Request correlation created: {correlation_id}",
            context={'component': 'correlation', 'operation': 'create'},
            error_details={
                'correlation_id': correlation_id,
                'trace_id': trace_id,
                'agent_type': agent_type,
                'workflow_id': workflow_id
            }
        )
        
        return correlation
    
    def get_correlation(self, correlation_id: str) -> Optional[RequestCorrelation]:
        """Get correlation by ID."""
        with self._lock:
            return self._correlations.get(correlation_id)
    
    def get_current_correlation(self) -> Optional[RequestCorrelation]:
        """Get the current correlation from context."""
        return request_correlation_var.get()
    
    def set_current_correlation(self, correlation: RequestCorrelation):
        """Set the current correlation in context."""
        request_correlation_var.set(correlation)
    
    def clear_current_correlation(self):
        """Clear the current correlation from context."""
        request_correlation_var.set(None)
    
    def finish_correlation(self, correlation_id: str):
        """Finish a correlation and clean up."""
        with self._lock:
            correlation = self._correlations.get(correlation_id)
            if correlation:
                # Finish any active spans
                for span in correlation.get_active_spans():
                    span.finish()
                
                # Log completion
                self.structured_logger.info(
                    f"Request correlation finished: {correlation_id}",
                    context={'component': 'correlation', 'operation': 'finish'},
                    performance_metrics={
                        'correlation_id': correlation_id,
                        'duration_ms': correlation.get_duration_ms(),
                        'spans_count': len(correlation.spans),
                        'active_spans': len(correlation.get_active_spans())
                    }
                )
                
                # Record metrics
                self.metrics.observe_histogram(
                    "request_correlation_duration_seconds",
                    {'agent_type': correlation.agent_type or 'unknown'},
                    correlation.get_duration_ms() / 1000
                )
                
                # Keep for a short time for debugging, then remove
                # (actual cleanup happens in background thread)
    
    def _cleanup_old_correlations(self):
        """Background thread to clean up old correlations."""
        while True:
            try:
                time.sleep(300)  # Run every 5 minutes
                
                current_time = time.time()
                cutoff_time = current_time - 3600  # Remove correlations older than 1 hour
                
                with self._lock:
                    expired_ids = [
                        corr_id for corr_id, corr in self._correlations.items()
                        if corr.request_start_time < cutoff_time
                    ]
                    
                    for corr_id in expired_ids:
                        del self._correlations[corr_id]
                
                if expired_ids:
                    self.structured_logger.debug(
                        f"Cleaned up {len(expired_ids)} expired correlations",
                        context={'component': 'correlation', 'operation': 'cleanup'}
                    )
            
            except Exception as e:
                self.structured_logger.error(
                    f"Error in correlation cleanup: {e}",
                    context={'component': 'correlation', 'operation': 'cleanup_error'}
                )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tracker statistics."""
        with self._lock:
            total_correlations = len(self._correlations)
            active_spans = sum(
                len(corr.get_active_spans()) 
                for corr in self._correlations.values()
            )
            
            return {
                'total_correlations': total_correlations,
                'active_spans': active_spans,
                'avg_spans_per_correlation': (
                    sum(len(corr.spans) for corr in self._correlations.values()) / 
                    total_correlations if total_correlations > 0 else 0
                )
            }


class CorrelationContext:
    """Context manager for request correlation."""
    
    def __init__(
        self,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_type: Optional[str] = None,
        workflow_id: Optional[str] = None,
        tracker: Optional[CorrelationTracker] = None,
        **metadata
    ):
        self.tracker = tracker or get_correlation_tracker()
        self.correlation = self.tracker.create_correlation(
            correlation_id=correlation_id,
            trace_id=trace_id,
            user_id=user_id,
            session_id=session_id,
            agent_type=agent_type,
            workflow_id=workflow_id,
            **metadata
        )
        self._previous_correlation = None
    
    def __enter__(self) -> RequestCorrelation:
        self._previous_correlation = self.tracker.get_current_correlation()
        self.tracker.set_current_correlation(self.correlation)
        return self.correlation
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.tracker.finish_correlation(self.correlation.correlation_id)
        self.tracker.set_current_correlation(self._previous_correlation)


class SpanContext:
    """Context manager for distributed tracing spans."""
    
    def __init__(
        self,
        operation_name: str,
        parent_span_id: Optional[str] = None,
        correlation: Optional[RequestCorrelation] = None,
        **tags
    ):
        self.operation_name = operation_name
        self.parent_span_id = parent_span_id
        self.tags = tags
        self.correlation = correlation or get_correlation_tracker().get_current_correlation()
        self.span: Optional[TraceSpan] = None
    
    def __enter__(self) -> Optional[TraceSpan]:
        if self.correlation:
            self.span = self.correlation.create_span(
                operation_name=self.operation_name,
                parent_span_id=self.parent_span_id,
                **self.tags
            )
        return self.span
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.span:
            if exc_type is not None:
                self.span.set_error(exc_val)
            self.span.finish()


# Global correlation tracker
_correlation_tracker: Optional[CorrelationTracker] = None
_tracker_lock = threading.Lock()


def get_correlation_tracker() -> CorrelationTracker:
    """Get or create the global correlation tracker."""
    global _correlation_tracker
    
    if _correlation_tracker is None:
        with _tracker_lock:
            if _correlation_tracker is None:
                _correlation_tracker = CorrelationTracker()
    
    return _correlation_tracker


def init_correlation_tracker() -> CorrelationTracker:
    """Initialize the global correlation tracker."""
    global _correlation_tracker
    
    with _tracker_lock:
        _correlation_tracker = CorrelationTracker()
    
    return _correlation_tracker


# Convenience functions
def create_correlation(**kwargs) -> RequestCorrelation:
    """Create a new request correlation."""
    tracker = get_correlation_tracker()
    return tracker.create_correlation(**kwargs)


def get_current_correlation() -> Optional[RequestCorrelation]:
    """Get the current correlation from context."""
    tracker = get_correlation_tracker()
    return tracker.get_current_correlation()


def create_span(operation_name: str, **kwargs) -> Optional[TraceSpan]:
    """Create a span in the current correlation."""
    correlation = get_current_correlation()
    if correlation:
        return correlation.create_span(operation_name, **kwargs)
    return None


def add_correlation_metadata(key: str, value: Any):
    """Add metadata to the current correlation."""
    correlation = get_current_correlation()
    if correlation:
        correlation.add_metadata(key, value)


def span(operation_name: str, **tags):
    """Decorator to automatically create spans for functions."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            with SpanContext(operation_name, **tags) as span:
                if span:
                    span.add_tag('function', func.__name__)
                    span.add_tag('module', func.__module__)
                
                try:
                    result = func(*args, **kwargs)
                    if span:
                        span.add_tag('success', True)
                    return result
                except Exception as e:
                    if span:
                        span.set_error(e)
                    raise
        
        return wrapper
    return decorator


# WHERE clause specific correlation functions
def create_where_clause_correlation(
    agent_type: str,
    where_clause: str,
    scope: str,
    user_id: Optional[str] = None,
    workflow_id: Optional[str] = None
) -> RequestCorrelation:
    """Create correlation specifically for WHERE clause operations."""
    correlation = create_correlation(
        user_id=user_id,
        agent_type=agent_type,
        workflow_id=workflow_id,
        where_clause=where_clause,
        scope=scope,
        operation_type="where_clause_evaluation"
    )
    
    # Create initial span
    root_span = correlation.create_span(
        "where_clause_evaluation",
        where_clause_length=len(where_clause),
        scope=scope,
        agent_type=agent_type
    )
    
    return correlation


def where_clause_span(operation_name: str, **tags):
    """Decorator for WHERE clause operation spans."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Extract WHERE clause specific information if available
            extra_tags = tags.copy()
            
            # Try to extract agent_type and other context from arguments
            if args and hasattr(args[0], '__dict__'):
                obj = args[0]
                if hasattr(obj, 'agent_type'):
                    extra_tags['agent_type'] = obj.agent_type
            
            with SpanContext(operation_name, **extra_tags) as span:
                if span:
                    span.add_tag('function', func.__name__)
                    span.add_tag('component', 'where_clause')
                
                try:
                    result = func(*args, **kwargs)
                    if span:
                        span.add_tag('success', True)
                        # Add result metadata if it's useful
                        if isinstance(result, (list, tuple)):
                            span.add_tag('result_count', len(result))
                        elif isinstance(result, bool):
                            span.add_tag('result', result)
                    return result
                except Exception as e:
                    if span:
                        span.set_error(e)
                    raise
        
        return wrapper
    return decorator