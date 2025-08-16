"""
Production-grade metrics collection for WHERE clause filtering.
Implements Prometheus metrics for comprehensive observability.
"""
import time
import functools
from typing import Dict, Any, Optional, List, Callable
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

try:
    from prometheus_client import Counter, Histogram, Gauge, Info, CollectorRegistry, start_http_server
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

import logging
import threading
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics we can collect."""
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    GAUGE = "gauge"
    INFO = "info"


@dataclass
class MetricConfig:
    """Configuration for a metric."""
    name: str
    description: str
    labels: List[str]
    metric_type: MetricType
    buckets: Optional[List[float]] = None  # For histograms


class MetricsCollector:
    """
    Production-grade metrics collector with Prometheus integration.
    Falls back to in-memory metrics if Prometheus is not available.
    """
    
    def __init__(self, registry: Optional[CollectorRegistry] = None, enable_prometheus: bool = True):
        self.enable_prometheus = enable_prometheus and PROMETHEUS_AVAILABLE
        self.registry = registry if self.enable_prometheus else None
        self.metrics: Dict[str, Any] = {}
        self.fallback_metrics: Dict[str, Any] = defaultdict(dict)
        self._lock = threading.RLock()
        
        # Initialize metrics
        self._initialize_where_clause_metrics()
        
        if not self.enable_prometheus:
            logger.warning("Prometheus not available. Using in-memory metrics fallback.")
    
    def _initialize_where_clause_metrics(self):
        """Initialize WHERE clause specific metrics."""
        metrics_config = [
            MetricConfig(
                name="where_clause_evaluations_total",
                description="Total number of WHERE clause evaluations",
                labels=["status", "scope", "agent_type"],
                metric_type=MetricType.COUNTER
            ),
            MetricConfig(
                name="where_clause_evaluation_duration_seconds",
                description="Time spent evaluating WHERE clauses",
                labels=["scope", "agent_type", "complexity"],
                metric_type=MetricType.HISTOGRAM,
                buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
            ),
            MetricConfig(
                name="where_clause_conditions_count",
                description="Number of conditions in WHERE clauses",
                labels=["agent_type"],
                metric_type=MetricType.HISTOGRAM,
                buckets=[1, 2, 3, 5, 10, 20, 50]
            ),
            MetricConfig(
                name="where_clause_cache_hits_total",
                description="Number of WHERE clause cache hits",
                labels=["cache_type"],
                metric_type=MetricType.COUNTER
            ),
            MetricConfig(
                name="where_clause_cache_misses_total",
                description="Number of WHERE clause cache misses",
                labels=["cache_type"],
                metric_type=MetricType.COUNTER
            ),
            MetricConfig(
                name="where_clause_errors_total",
                description="Total number of WHERE clause evaluation errors",
                labels=["error_type", "agent_type", "scope"],
                metric_type=MetricType.COUNTER
            ),
            MetricConfig(
                name="where_clause_filtered_items_total",
                description="Total number of items filtered by WHERE clauses",
                labels=["agent_type", "filter_result"],
                metric_type=MetricType.COUNTER
            ),
            MetricConfig(
                name="where_clause_circuit_breaker_state",
                description="Current state of WHERE clause circuit breakers",
                labels=["agent_type", "state"],
                metric_type=MetricType.GAUGE
            ),
            MetricConfig(
                name="where_clause_feature_flag_status",
                description="Feature flag status for WHERE clause functionality",
                labels=["flag_name", "agent_type"],
                metric_type=MetricType.GAUGE
            ),
            MetricConfig(
                name="where_clause_request_correlation",
                description="Request correlation tracking",
                labels=["correlation_id", "agent_type"],
                metric_type=MetricType.INFO
            )
        ]
        
        for config in metrics_config:
            self._create_metric(config)
    
    def _create_metric(self, config: MetricConfig):
        """Create a metric based on configuration."""
        with self._lock:
            if self.enable_prometheus:
                if config.metric_type == MetricType.COUNTER:
                    metric = Counter(
                        config.name, 
                        config.description, 
                        config.labels,
                        registry=self.registry
                    )
                elif config.metric_type == MetricType.HISTOGRAM:
                    metric = Histogram(
                        config.name,
                        config.description,
                        config.labels,
                        buckets=config.buckets,
                        registry=self.registry
                    )
                elif config.metric_type == MetricType.GAUGE:
                    metric = Gauge(
                        config.name,
                        config.description,
                        config.labels,
                        registry=self.registry
                    )
                elif config.metric_type == MetricType.INFO:
                    metric = Info(
                        config.name,
                        config.description,
                        registry=self.registry
                    )
                else:
                    raise ValueError(f"Unknown metric type: {config.metric_type}")
                
                self.metrics[config.name] = metric
            else:
                # Fallback to in-memory tracking
                self.fallback_metrics[config.name] = {
                    'type': config.metric_type,
                    'description': config.description,
                    'labels': config.labels,
                    'values': defaultdict(float),
                    'samples': deque(maxlen=1000)  # Keep last 1000 samples for histograms
                }
    
    def increment_counter(self, metric_name: str, labels: Dict[str, str], value: float = 1.0):
        """Increment a counter metric."""
        with self._lock:
            if self.enable_prometheus and metric_name in self.metrics:
                self.metrics[metric_name].labels(**labels).inc(value)
            else:
                # Fallback
                label_key = self._serialize_labels(labels)
                self.fallback_metrics[metric_name]['values'][label_key] += value
    
    def observe_histogram(self, metric_name: str, labels: Dict[str, str], value: float):
        """Observe a value in a histogram metric."""
        with self._lock:
            if self.enable_prometheus and metric_name in self.metrics:
                self.metrics[metric_name].labels(**labels).observe(value)
            else:
                # Fallback
                label_key = self._serialize_labels(labels)
                self.fallback_metrics[metric_name]['samples'].append((label_key, value, time.time()))
    
    def set_gauge(self, metric_name: str, labels: Dict[str, str], value: float):
        """Set a gauge metric value."""
        with self._lock:
            if self.enable_prometheus and metric_name in self.metrics:
                self.metrics[metric_name].labels(**labels).set(value)
            else:
                # Fallback
                label_key = self._serialize_labels(labels)
                self.fallback_metrics[metric_name]['values'][label_key] = value
    
    def set_info(self, metric_name: str, info_dict: Dict[str, str]):
        """Set an info metric."""
        with self._lock:
            if self.enable_prometheus and metric_name in self.metrics:
                self.metrics[metric_name].info(info_dict)
            else:
                # Fallback
                self.fallback_metrics[metric_name]['values']['info'] = info_dict
    
    @contextmanager
    def timer(self, metric_name: str, labels: Dict[str, str]):
        """Context manager for timing operations."""
        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            self.observe_histogram(metric_name, labels, duration)
    
    def _serialize_labels(self, labels: Dict[str, str]) -> str:
        """Serialize labels for fallback storage."""
        return "|".join(f"{k}={v}" for k, v in sorted(labels.items()))
    
    def get_fallback_metrics(self) -> Dict[str, Any]:
        """Get fallback metrics for debugging/monitoring."""
        with self._lock:
            return dict(self.fallback_metrics)
    
    def start_metrics_server(self, port: int = 8000):
        """Start Prometheus metrics server."""
        if self.enable_prometheus:
            start_http_server(port, registry=self.registry)
            logger.info(f"Metrics server started on port {port}")
        else:
            logger.warning("Cannot start metrics server: Prometheus not available")


# Global metrics instance
_metrics_collector: Optional[MetricsCollector] = None
_metrics_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """Get or create the global metrics collector."""
    global _metrics_collector
    
    if _metrics_collector is None:
        with _metrics_lock:
            if _metrics_collector is None:
                _metrics_collector = MetricsCollector()
    
    return _metrics_collector


def init_metrics(registry: Optional[CollectorRegistry] = None, enable_prometheus: bool = True) -> MetricsCollector:
    """Initialize the global metrics collector."""
    global _metrics_collector
    
    with _metrics_lock:
        _metrics_collector = MetricsCollector(registry=registry, enable_prometheus=enable_prometheus)
    
    return _metrics_collector


def metrics_decorator(metric_name: str, labels_func: Optional[Callable] = None, record_duration: bool = True):
    """
    Decorator to automatically record metrics for function calls.
    
    Args:
        metric_name: Base name for metrics
        labels_func: Function to extract labels from function args/kwargs
        record_duration: Whether to record execution duration
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            collector = get_metrics_collector()
            
            # Extract labels
            labels = {}
            if labels_func:
                try:
                    labels = labels_func(*args, **kwargs)
                except Exception as e:
                    logger.warning(f"Failed to extract labels for {func.__name__}: {e}")
            
            # Add function name to labels
            labels.setdefault('function', func.__name__)
            
            # Record call count
            collector.increment_counter(f"{metric_name}_calls_total", labels)
            
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                # Record success
                success_labels = labels.copy()
                success_labels['status'] = 'success'
                collector.increment_counter(f"{metric_name}_total", success_labels)
                return result
            except Exception as e:
                # Record error
                error_labels = labels.copy()
                error_labels['status'] = 'error'
                error_labels['error_type'] = type(e).__name__
                collector.increment_counter(f"{metric_name}_total", error_labels)
                raise
            finally:
                if record_duration:
                    duration = time.time() - start_time
                    collector.observe_histogram(f"{metric_name}_duration_seconds", labels, duration)
        
        return wrapper
    return decorator


# Convenience functions for WHERE clause metrics
def record_where_clause_evaluation(scope: str, agent_type: str, status: str, duration: float):
    """Record a WHERE clause evaluation."""
    collector = get_metrics_collector()
    
    labels = {
        'scope': scope,
        'agent_type': agent_type,
        'status': status
    }
    
    # Determine complexity based on duration
    if duration < 0.001:
        complexity = 'simple'
    elif duration < 0.01:
        complexity = 'medium'
    else:
        complexity = 'complex'
    
    eval_labels = labels.copy()
    eval_labels['complexity'] = complexity
    
    collector.increment_counter("where_clause_evaluations_total", labels)
    collector.observe_histogram("where_clause_evaluation_duration_seconds", eval_labels, duration)


def record_where_clause_cache_hit(cache_type: str):
    """Record a cache hit."""
    collector = get_metrics_collector()
    collector.increment_counter("where_clause_cache_hits_total", {'cache_type': cache_type})


def record_where_clause_cache_miss(cache_type: str):
    """Record a cache miss."""
    collector = get_metrics_collector()
    collector.increment_counter("where_clause_cache_misses_total", {'cache_type': cache_type})


def record_where_clause_error(error_type: str, agent_type: str, scope: str):
    """Record a WHERE clause error."""
    collector = get_metrics_collector()
    collector.increment_counter("where_clause_errors_total", {
        'error_type': error_type,
        'agent_type': agent_type,
        'scope': scope
    })


def record_where_clause_filter_result(agent_type: str, filter_result: str, count: int = 1):
    """Record filtering results."""
    collector = get_metrics_collector()
    collector.increment_counter("where_clause_filtered_items_total", {
        'agent_type': agent_type,
        'filter_result': filter_result
    }, count)


def set_circuit_breaker_state(agent_type: str, state: str):
    """Set circuit breaker state."""
    collector = get_metrics_collector()
    state_value = {'open': 0, 'half_open': 1, 'closed': 2}.get(state.lower(), -1)
    collector.set_gauge("where_clause_circuit_breaker_state", {
        'agent_type': agent_type,
        'state': state
    }, state_value)


def set_feature_flag_status(flag_name: str, agent_type: str, enabled: bool):
    """Set feature flag status."""
    collector = get_metrics_collector()
    collector.set_gauge("where_clause_feature_flag_status", {
        'flag_name': flag_name,
        'agent_type': agent_type
    }, 1.0 if enabled else 0.0)


def set_request_correlation(correlation_id: str, agent_type: str, metadata: Dict[str, str]):
    """Set request correlation info."""
    collector = get_metrics_collector()
    info_dict = metadata.copy()
    info_dict['correlation_id'] = correlation_id
    info_dict['agent_type'] = agent_type
    collector.set_info("where_clause_request_correlation", info_dict)