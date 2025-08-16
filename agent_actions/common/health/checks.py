"""
Production-grade health checks and debugging endpoints.
Provides comprehensive system health monitoring and debugging capabilities.
"""
import time
import threading
import psutil
import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime, timedelta
import logging

from ..monitoring.metrics import get_metrics_collector
from ..monitoring.logging import get_logger
from ..resilience.circuit_breaker import get_all_circuit_breakers
from ..feature_flags.manager import get_feature_flag_manager
from ..correlation.tracker import get_correlation_tracker
from ..filters.secure_parser import get_secure_parser

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health check status enumeration."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    name: str
    status: HealthStatus
    message: str
    timestamp: str
    duration_ms: float
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class SystemHealth:
    """Overall system health status."""
    status: HealthStatus
    timestamp: str
    checks: List[HealthCheckResult]
    summary: Dict[str, Any]
    uptime_seconds: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'status': self.status.value,
            'timestamp': self.timestamp,
            'uptime_seconds': self.uptime_seconds,
            'summary': self.summary,
            'checks': [check.to_dict() for check in self.checks]
        }


class HealthCheck:
    """Base class for health checks."""
    
    def __init__(self, name: str, timeout_ms: float = 5000):
        self.name = name
        self.timeout_ms = timeout_ms
    
    def check(self) -> HealthCheckResult:
        """Perform the health check."""
        start_time = time.time()
        
        try:
            status, message, metadata = self._perform_check()
            duration_ms = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                name=self.name,
                status=status,
                message=message,
                timestamp=datetime.utcnow().isoformat() + "Z",
                duration_ms=duration_ms,
                metadata=metadata or {}
            )
        
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {str(e)}",
                timestamp=datetime.utcnow().isoformat() + "Z",
                duration_ms=duration_ms,
                metadata={'error_type': type(e).__name__, 'error_message': str(e)}
            )
    
    def _perform_check(self) -> tuple[HealthStatus, str, Optional[Dict[str, Any]]]:
        """Implement the actual health check logic."""
        raise NotImplementedError


class SystemResourcesHealthCheck(HealthCheck):
    """Health check for system resources."""
    
    def __init__(self):
        super().__init__("system_resources")
    
    def _perform_check(self) -> tuple[HealthStatus, str, Optional[Dict[str, Any]]]:
        """Check system resources."""
        # Get system metrics
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        metadata = {
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'memory_available_mb': memory.available / 1024 / 1024,
            'disk_percent': disk.percent,
            'disk_free_gb': disk.free / 1024 / 1024 / 1024
        }
        
        # Determine status based on thresholds
        if cpu_percent > 90 or memory.percent > 90 or disk.percent > 95:
            return HealthStatus.CRITICAL, "System resources critically low", metadata
        elif cpu_percent > 80 or memory.percent > 80 or disk.percent > 90:
            return HealthStatus.DEGRADED, "System resources under pressure", metadata
        elif cpu_percent > 70 or memory.percent > 70 or disk.percent > 85:
            return HealthStatus.DEGRADED, "System resources elevated", metadata
        else:
            return HealthStatus.HEALTHY, "System resources normal", metadata


class WhereClauseHealthCheck(HealthCheck):
    """Health check for WHERE clause functionality."""
    
    def __init__(self):
        super().__init__("where_clause")
    
    def _perform_check(self) -> tuple[HealthStatus, str, Optional[Dict[str, Any]]]:
        """Check WHERE clause functionality."""
        try:
            parser = get_secure_parser()
            
            # Test basic parsing
            test_clause = 'test_field == "test_value"'
            conditions = parser.parse(test_clause, "health_check")
            
            # Test evaluation
            test_data = {'test_field': 'test_value'}
            result = parser.evaluate(test_data, conditions, "health_check")
            
            if not result:
                return HealthStatus.UNHEALTHY, "WHERE clause evaluation failed", {
                    'test_clause': test_clause,
                    'test_data': test_data,
                    'expected_result': True,
                    'actual_result': result
                }
            
            # Get cache stats
            cache_stats = parser.get_cache_stats()
            
            metadata = {
                'parser_status': 'operational',
                'test_passed': True,
                'cache_stats': cache_stats
            }
            
            return HealthStatus.HEALTHY, "WHERE clause functionality operational", metadata
        
        except Exception as e:
            return HealthStatus.UNHEALTHY, f"WHERE clause check failed: {str(e)}", {
                'error_type': type(e).__name__,
                'error_message': str(e)
            }


class CircuitBreakerHealthCheck(HealthCheck):
    """Health check for circuit breakers."""
    
    def __init__(self):
        super().__init__("circuit_breakers")
    
    def _perform_check(self) -> tuple[HealthStatus, str, Optional[Dict[str, Any]]]:
        """Check circuit breaker states."""
        breakers = get_all_circuit_breakers()
        
        if not breakers:
            return HealthStatus.HEALTHY, "No circuit breakers configured", {'breaker_count': 0}
        
        breaker_stats = {}
        open_breakers = 0
        half_open_breakers = 0
        
        for name, breaker in breakers.items():
            stats = breaker.get_stats()
            breaker_stats[name] = stats
            
            if stats['state'] == 'open':
                open_breakers += 1
            elif stats['state'] == 'half_open':
                half_open_breakers += 1
        
        metadata = {
            'breaker_count': len(breakers),
            'open_breakers': open_breakers,
            'half_open_breakers': half_open_breakers,
            'breaker_details': breaker_stats
        }
        
        # Determine status
        if open_breakers > 0:
            return HealthStatus.DEGRADED, f"{open_breakers} circuit breakers are open", metadata
        elif half_open_breakers > 0:
            return HealthStatus.DEGRADED, f"{half_open_breakers} circuit breakers are half-open", metadata
        else:
            return HealthStatus.HEALTHY, "All circuit breakers are closed", metadata


class FeatureFlagHealthCheck(HealthCheck):
    """Health check for feature flag system."""
    
    def __init__(self):
        super().__init__("feature_flags")
    
    def _perform_check(self) -> tuple[HealthStatus, str, Optional[Dict[str, Any]]]:
        """Check feature flag system."""
        try:
            manager = get_feature_flag_manager()
            flags_status = manager.get_all_flags_status()
            
            # Check for emergency kill switches
            emergency_switches = 0
            for flag_name, flag_status in flags_status.items():
                if flag_status and flag_status.get('emergency_kill_switch'):
                    emergency_switches += 1
            
            metadata = {
                'total_flags': len(flags_status),
                'emergency_switches_active': emergency_switches,
                'flag_summary': {
                    name: {
                        'enabled': status.get('enabled', False) if status else False,
                        'emergency_kill_switch': status.get('emergency_kill_switch', False) if status else False
                    }
                    for name, status in flags_status.items()
                }
            }
            
            if emergency_switches > 0:
                return HealthStatus.DEGRADED, f"{emergency_switches} emergency kill switches are active", metadata
            else:
                return HealthStatus.HEALTHY, "Feature flag system operational", metadata
        
        except Exception as e:
            return HealthStatus.UNHEALTHY, f"Feature flag check failed: {str(e)}", {
                'error_type': type(e).__name__,
                'error_message': str(e)
            }


class CorrelationHealthCheck(HealthCheck):
    """Health check for request correlation system."""
    
    def __init__(self):
        super().__init__("correlation")
    
    def _perform_check(self) -> tuple[HealthStatus, str, Optional[Dict[str, Any]]]:
        """Check correlation tracking system."""
        try:
            tracker = get_correlation_tracker()
            stats = tracker.get_stats()
            
            metadata = {
                'correlation_stats': stats
            }
            
            # Check for excessive active correlations (potential memory leak)
            if stats['total_correlations'] > 10000:
                return HealthStatus.DEGRADED, "High number of active correlations", metadata
            elif stats['active_spans'] > 50000:
                return HealthStatus.DEGRADED, "High number of active spans", metadata
            else:
                return HealthStatus.HEALTHY, "Correlation tracking operational", metadata
        
        except Exception as e:
            return HealthStatus.UNHEALTHY, f"Correlation check failed: {str(e)}", {
                'error_type': type(e).__name__,
                'error_message': str(e)
            }


class MetricsHealthCheck(HealthCheck):
    """Health check for metrics system."""
    
    def __init__(self):
        super().__init__("metrics")
    
    def _perform_check(self) -> tuple[HealthStatus, str, Optional[Dict[str, Any]]]:
        """Check metrics collection system."""
        try:
            metrics = get_metrics_collector()
            
            # Try to record a test metric
            metrics.increment_counter("health_check_test", {'source': 'health_check'})
            
            # Get fallback metrics if available
            fallback_metrics = metrics.get_fallback_metrics()
            
            metadata = {
                'prometheus_available': metrics.enable_prometheus,
                'fallback_metrics_count': len(fallback_metrics) if fallback_metrics else 0
            }
            
            return HealthStatus.HEALTHY, "Metrics system operational", metadata
        
        except Exception as e:
            return HealthStatus.UNHEALTHY, f"Metrics check failed: {str(e)}", {
                'error_type': type(e).__name__,
                'error_message': str(e)
            }


class HealthMonitor:
    """
    Production-grade health monitoring system.
    Coordinates health checks and provides comprehensive system status.
    """
    
    def __init__(self):
        self.start_time = time.time()
        self.health_checks: List[HealthCheck] = []
        self.structured_logger = get_logger()
        self._lock = threading.RLock()
        
        # Register default health checks
        self._register_default_checks()
    
    def _register_default_checks(self):
        """Register default health checks."""
        default_checks = [
            SystemResourcesHealthCheck(),
            WhereClauseHealthCheck(),
            CircuitBreakerHealthCheck(),
            FeatureFlagHealthCheck(),
            CorrelationHealthCheck(),
            MetricsHealthCheck()
        ]
        
        for check in default_checks:
            self.register_health_check(check)
    
    def register_health_check(self, health_check: HealthCheck):
        """Register a health check."""
        with self._lock:
            self.health_checks.append(health_check)
        
        self.structured_logger.info(
            f"Health check registered: {health_check.name}",
            context={'component': 'health_monitor', 'operation': 'register_check'}
        )
    
    def remove_health_check(self, name: str):
        """Remove a health check by name."""
        with self._lock:
            self.health_checks = [check for check in self.health_checks if check.name != name]
    
    def check_health(self, check_names: Optional[List[str]] = None) -> SystemHealth:
        """
        Perform health checks and return overall system health.
        
        Args:
            check_names: Optional list of specific checks to run
            
        Returns:
            SystemHealth object with overall status and individual check results
        """
        start_time = time.time()
        
        # Determine which checks to run
        if check_names:
            checks_to_run = [
                check for check in self.health_checks 
                if check.name in check_names
            ]
        else:
            checks_to_run = self.health_checks.copy()
        
        # Run checks
        results = []
        for check in checks_to_run:
            try:
                result = check.check()
                results.append(result)
            except Exception as e:
                # Create failed result for check that threw exception
                result = HealthCheckResult(
                    name=check.name,
                    status=HealthStatus.CRITICAL,
                    message=f"Health check crashed: {str(e)}",
                    timestamp=datetime.utcnow().isoformat() + "Z",
                    duration_ms=(time.time() - start_time) * 1000,
                    metadata={'error_type': type(e).__name__, 'error_message': str(e)}
                )
                results.append(result)
                
                self.structured_logger.error(
                    f"Health check {check.name} crashed: {e}",
                    context={'component': 'health_monitor', 'operation': 'check_health'},
                    error_details={
                        'check_name': check.name,
                        'exception_type': type(e).__name__,
                        'exception_message': str(e)
                    }
                )
        
        # Determine overall status
        overall_status = self._determine_overall_status(results)
        
        # Create summary
        summary = self._create_summary(results)
        
        # Calculate uptime
        uptime_seconds = time.time() - self.start_time
        
        system_health = SystemHealth(
            status=overall_status,
            timestamp=datetime.utcnow().isoformat() + "Z",
            checks=results,
            summary=summary,
            uptime_seconds=uptime_seconds
        )
        
        # Log health check completion
        self.structured_logger.info(
            f"Health check completed: {overall_status.value}",
            context={'component': 'health_monitor', 'operation': 'check_health'},
            performance_metrics={
                'overall_status': overall_status.value,
                'checks_count': len(results),
                'duration_ms': (time.time() - start_time) * 1000
            }
        )
        
        return system_health
    
    def _determine_overall_status(self, results: List[HealthCheckResult]) -> HealthStatus:
        """Determine overall system status from individual check results."""
        if not results:
            return HealthStatus.UNHEALTHY
        
        # Count status types
        status_counts = {
            HealthStatus.HEALTHY: 0,
            HealthStatus.DEGRADED: 0,
            HealthStatus.UNHEALTHY: 0,
            HealthStatus.CRITICAL: 0
        }
        
        for result in results:
            status_counts[result.status] += 1
        
        # Determine overall status based on worst case
        if status_counts[HealthStatus.CRITICAL] > 0:
            return HealthStatus.CRITICAL
        elif status_counts[HealthStatus.UNHEALTHY] > 0:
            return HealthStatus.UNHEALTHY
        elif status_counts[HealthStatus.DEGRADED] > 0:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY
    
    def _create_summary(self, results: List[HealthCheckResult]) -> Dict[str, Any]:
        """Create summary of health check results."""
        total_checks = len(results)
        if total_checks == 0:
            return {'total_checks': 0}
        
        # Count by status
        status_counts = {status.value: 0 for status in HealthStatus}
        total_duration = 0
        
        for result in results:
            status_counts[result.status.value] += 1
            total_duration += result.duration_ms
        
        return {
            'total_checks': total_checks,
            'status_counts': status_counts,
            'avg_check_duration_ms': total_duration / total_checks,
            'healthy_percentage': (status_counts['healthy'] / total_checks) * 100
        }
    
    def get_detailed_status(self) -> Dict[str, Any]:
        """Get detailed system status including internal metrics."""
        health = self.check_health()
        
        # Add additional detailed information
        detailed_status = health.to_dict()
        
        # Add system information
        detailed_status['system_info'] = {
            'python_version': f"{psutil.sys.version_info.major}.{psutil.sys.version_info.minor}.{psutil.sys.version_info.micro}",
            'platform': psutil.sys.platform,
            'boot_time': datetime.fromtimestamp(psutil.boot_time()).isoformat(),
            'process_count': len(psutil.pids())
        }
        
        # Add component-specific debugging info
        detailed_status['debug_info'] = self._get_debug_info()
        
        return detailed_status
    
    def _get_debug_info(self) -> Dict[str, Any]:
        """Get debugging information from various components."""
        debug_info = {}
        
        try:
            # WHERE clause parser debug info
            parser = get_secure_parser()
            debug_info['where_clause_parser'] = {
                'cache_stats': parser.get_cache_stats(),
                'security_context': {
                    'max_clause_length': parser.security_context.max_clause_length,
                    'max_conditions': parser.security_context.max_conditions,
                    'max_evaluation_time_ms': parser.security_context.max_evaluation_time_ms
                }
            }
        except Exception as e:
            debug_info['where_clause_parser'] = {'error': str(e)}
        
        try:
            # Circuit breaker debug info
            breakers = get_all_circuit_breakers()
            debug_info['circuit_breakers'] = {
                name: breaker.get_stats() 
                for name, breaker in breakers.items()
            }
        except Exception as e:
            debug_info['circuit_breakers'] = {'error': str(e)}
        
        try:
            # Feature flags debug info
            manager = get_feature_flag_manager()
            debug_info['feature_flags'] = manager.get_all_flags_status()
        except Exception as e:
            debug_info['feature_flags'] = {'error': str(e)}
        
        try:
            # Correlation tracker debug info
            tracker = get_correlation_tracker()
            debug_info['correlation'] = tracker.get_stats()
        except Exception as e:
            debug_info['correlation'] = {'error': str(e)}
        
        return debug_info


# Global health monitor instance
_health_monitor: Optional[HealthMonitor] = None
_monitor_lock = threading.Lock()


def get_health_monitor() -> HealthMonitor:
    """Get or create the global health monitor."""
    global _health_monitor
    
    if _health_monitor is None:
        with _monitor_lock:
            if _health_monitor is None:
                _health_monitor = HealthMonitor()
    
    return _health_monitor


def init_health_monitor() -> HealthMonitor:
    """Initialize the global health monitor."""
    global _health_monitor
    
    with _monitor_lock:
        _health_monitor = HealthMonitor()
    
    return _health_monitor


# Convenience functions
def check_system_health() -> SystemHealth:
    """Check overall system health."""
    monitor = get_health_monitor()
    return monitor.check_health()


def check_specific_health(check_names: List[str]) -> SystemHealth:
    """Check specific health components."""
    monitor = get_health_monitor()
    return monitor.check_health(check_names)


def get_health_status() -> Dict[str, Any]:
    """Get health status as dictionary."""
    health = check_system_health()
    return health.to_dict()


def get_detailed_health_status() -> Dict[str, Any]:
    """Get detailed health status with debugging information."""
    monitor = get_health_monitor()
    return monitor.get_detailed_status()


def is_system_healthy() -> bool:
    """Simple boolean check if system is healthy."""
    health = check_system_health()
    return health.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)