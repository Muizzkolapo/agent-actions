"""
Production-grade circuit breaker implementation for WHERE clause filtering.
Provides fault tolerance and graceful degradation patterns.
"""
import time
import threading
import asyncio
from typing import Callable, Any, Optional, Dict, Union
from dataclasses import dataclass
from enum import Enum
from collections import deque
import functools
import logging

from ..monitoring.metrics import get_metrics_collector, set_circuit_breaker_state
from ..monitoring.logging import get_logger, log_security_violation

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0  # seconds
    success_threshold: int = 3  # for half-open state
    timeout: float = 30.0  # operation timeout
    expected_exception: tuple = (Exception,)
    fallback_function: Optional[Callable] = None
    name: str = "default"


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open."""
    pass


class TimeoutError(Exception):
    """Exception raised when operation times out."""
    pass


class CircuitBreaker:
    """
    Production-grade circuit breaker with metrics and monitoring.
    Implements the circuit breaker pattern with proper observability.
    """
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Metrics tracking
        self.metrics = get_metrics_collector()
        self.structured_logger = get_logger()
        
        # Recent failures for analysis
        self.recent_failures = deque(maxlen=100)
        
        # Initialize metrics
        self._update_metrics()
    
    def _update_metrics(self):
        """Update circuit breaker metrics."""
        set_circuit_breaker_state(self.config.name, self.state.value)
    
    def _should_attempt_reset(self) -> bool:
        """Check if we should attempt to reset from OPEN to HALF_OPEN."""
        if self.state != CircuitBreakerState.OPEN:
            return False
        
        if self.last_failure_time is None:
            return False
        
        return time.time() - self.last_failure_time >= self.config.recovery_timeout
    
    def _record_success(self):
        """Record a successful operation."""
        with self._lock:
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self.state = CircuitBreakerState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
                    self.structured_logger.info(
                        f"Circuit breaker {self.config.name} reset to CLOSED",
                        context={'component': 'circuit_breaker', 'operation': 'state_change'}
                    )
            elif self.state == CircuitBreakerState.CLOSED:
                # Reset failure count on success
                self.failure_count = 0
            
            self._update_metrics()
    
    def _record_failure(self, exception: Exception):
        """Record a failed operation."""
        with self._lock:
            current_time = time.time()
            
            # Record failure details
            failure_info = {
                'timestamp': current_time,
                'exception_type': type(exception).__name__,
                'exception_message': str(exception)
            }
            self.recent_failures.append(failure_info)
            
            if self.state == CircuitBreakerState.CLOSED:
                self.failure_count += 1
                if self.failure_count >= self.config.failure_threshold:
                    self.state = CircuitBreakerState.OPEN
                    self.last_failure_time = current_time
                    self.success_count = 0
                    
                    self.structured_logger.error(
                        f"Circuit breaker {self.config.name} opened due to failures",
                        context={'component': 'circuit_breaker', 'operation': 'state_change'},
                        error_details={
                            'failure_count': self.failure_count,
                            'failure_threshold': self.config.failure_threshold,
                            'recent_failures': list(self.recent_failures)[-5:]  # Last 5 failures
                        }
                    )
                    
                    # Log security event if there are suspicious patterns
                    self._analyze_failure_patterns()
            
            elif self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.OPEN
                self.last_failure_time = current_time
                self.success_count = 0
                
                self.structured_logger.warning(
                    f"Circuit breaker {self.config.name} returned to OPEN from HALF_OPEN",
                    context={'component': 'circuit_breaker', 'operation': 'state_change'}
                )
            
            self._update_metrics()
    
    def _analyze_failure_patterns(self):
        """Analyze failure patterns for security concerns."""
        if len(self.recent_failures) < 3:
            return
        
        recent = list(self.recent_failures)[-10:]  # Last 10 failures
        
        # Check for rapid succession failures (potential attack)
        rapid_failures = 0
        for i in range(1, len(recent)):
            time_diff = recent[i]['timestamp'] - recent[i-1]['timestamp']
            if time_diff < 1.0:  # Less than 1 second apart
                rapid_failures += 1
        
        if rapid_failures >= 5:
            log_security_violation(
                "rapid_circuit_breaker_failures",
                "high",
                {
                    "circuit_breaker": self.config.name,
                    "rapid_failures": rapid_failures,
                    "timespan_seconds": recent[-1]['timestamp'] - recent[0]['timestamp'],
                    "failure_types": [f['exception_type'] for f in recent]
                }
            )
        
        # Check for specific attack patterns
        injection_keywords = ['eval', 'exec', 'import', '__', 'script', 'javascript']
        for failure in recent:
            message = failure['exception_message'].lower()
            for keyword in injection_keywords:
                if keyword in message:
                    log_security_violation(
                        "potential_code_injection",
                        "critical",
                        {
                            "circuit_breaker": self.config.name,
                            "keyword": keyword,
                            "failure_message": failure['exception_message']
                        }
                    )
                    break
    
    def _execute_with_timeout(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with timeout."""
        if asyncio.iscoroutinefunction(func):
            # Async function
            return asyncio.wait_for(func(*args, **kwargs), timeout=self.config.timeout)
        else:
            # Sync function - use threading for timeout
            import concurrent.futures
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, *args, **kwargs)
                try:
                    return future.result(timeout=self.config.timeout)
                except concurrent.futures.TimeoutError:
                    raise TimeoutError(f"Operation timed out after {self.config.timeout} seconds")
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerError: When circuit breaker is open
            Various exceptions: From the wrapped function
        """
        with self._lock:
            # Check if we should attempt reset
            if self._should_attempt_reset():
                self.state = CircuitBreakerState.HALF_OPEN
                self.success_count = 0
                self.structured_logger.info(
                    f"Circuit breaker {self.config.name} moved to HALF_OPEN for testing",
                    context={'component': 'circuit_breaker', 'operation': 'state_change'}
                )
                self._update_metrics()
            
            # If open, fail fast
            if self.state == CircuitBreakerState.OPEN:
                if self.config.fallback_function:
                    self.structured_logger.debug(
                        f"Circuit breaker {self.config.name} is open, using fallback",
                        context={'component': 'circuit_breaker', 'operation': 'fallback'}
                    )
                    return self.config.fallback_function(*args, **kwargs)
                else:
                    raise CircuitBreakerError(
                        f"Circuit breaker {self.config.name} is open. "
                        f"Last failure: {self.last_failure_time}"
                    )
        
        # Execute the function
        start_time = time.time()
        try:
            result = self._execute_with_timeout(func, *args, **kwargs)
            execution_time = time.time() - start_time
            
            # Record success
            self._record_success()
            
            # Log performance if slow
            if execution_time > self.config.timeout * 0.8:  # 80% of timeout
                self.structured_logger.warning(
                    f"Slow operation detected in circuit breaker {self.config.name}",
                    context={'component': 'circuit_breaker', 'operation': 'performance_warning'},
                    performance_metrics={
                        'execution_time_ms': execution_time * 1000,
                        'timeout_ms': self.config.timeout * 1000,
                        'threshold_percentage': 80
                    }
                )
            
            return result
        
        except self.config.expected_exception as e:
            # Record failure
            self._record_failure(e)
            raise
        except Exception as e:
            # Unexpected exception - record and re-raise
            self._record_failure(e)
            self.structured_logger.error(
                f"Unexpected exception in circuit breaker {self.config.name}",
                context={'component': 'circuit_breaker', 'operation': 'unexpected_error'},
                error_details={
                    'exception_type': type(e).__name__,
                    'exception_message': str(e)
                }
            )
            raise
    
    async def acall(self, func: Callable, *args, **kwargs) -> Any:
        """Async version of call method."""
        # For async operations, we handle timeout differently
        if not asyncio.iscoroutinefunction(func):
            # Convert sync function to async
            loop = asyncio.get_event_loop()
            func = functools.partial(loop.run_in_executor, None, func)
        
        return self.call(func, *args, **kwargs)
    
    def get_state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        return self.state
    
    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        with self._lock:
            return {
                'state': self.state.value,
                'failure_count': self.failure_count,
                'success_count': self.success_count,
                'last_failure_time': self.last_failure_time,
                'recent_failures_count': len(self.recent_failures),
                'config': {
                    'failure_threshold': self.config.failure_threshold,
                    'recovery_timeout': self.config.recovery_timeout,
                    'success_threshold': self.config.success_threshold,
                    'timeout': self.config.timeout
                }
            }
    
    def reset(self):
        """Manually reset circuit breaker to closed state."""
        with self._lock:
            self.state = CircuitBreakerState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_time = None
            self.recent_failures.clear()
            
            self.structured_logger.info(
                f"Circuit breaker {self.config.name} manually reset",
                context={'component': 'circuit_breaker', 'operation': 'manual_reset'}
            )
            self._update_metrics()


def circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    success_threshold: int = 3,
    timeout: float = 30.0,
    expected_exception: tuple = (Exception,),
    fallback_function: Optional[Callable] = None,
    name: Optional[str] = None
):
    """
    Decorator to add circuit breaker protection to a function.
    
    Args:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Time to wait before attempting recovery
        success_threshold: Successes needed to close circuit from half-open
        timeout: Operation timeout in seconds
        expected_exception: Exceptions that trigger circuit breaker
        fallback_function: Function to call when circuit is open
        name: Circuit breaker name for metrics
    """
    def decorator(func: Callable) -> Callable:
        breaker_name = name or f"{func.__module__}.{func.__name__}"
        config = CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            success_threshold=success_threshold,
            timeout=timeout,
            expected_exception=expected_exception,
            fallback_function=fallback_function,
            name=breaker_name
        )
        breaker = CircuitBreaker(config)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return breaker.call(func, *args, **kwargs)
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await breaker.acall(func, *args, **kwargs)
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            async_wrapper._circuit_breaker = breaker
            return async_wrapper
        else:
            wrapper._circuit_breaker = breaker
            return wrapper
    
    return decorator


# Global circuit breaker registry
_circuit_breakers: Dict[str, CircuitBreaker] = {}
_breaker_lock = threading.Lock()


def get_circuit_breaker(name: str) -> Optional[CircuitBreaker]:
    """Get circuit breaker by name."""
    with _breaker_lock:
        return _circuit_breakers.get(name)


def register_circuit_breaker(name: str, breaker: CircuitBreaker):
    """Register a circuit breaker."""
    with _breaker_lock:
        _circuit_breakers[name] = breaker


def get_all_circuit_breakers() -> Dict[str, CircuitBreaker]:
    """Get all registered circuit breakers."""
    with _breaker_lock:
        return _circuit_breakers.copy()


def get_circuit_breaker_stats() -> Dict[str, Dict[str, Any]]:
    """Get statistics for all circuit breakers."""
    with _breaker_lock:
        return {name: breaker.get_stats() for name, breaker in _circuit_breakers.items()}


# Convenience functions for WHERE clause circuit breakers
def create_where_clause_circuit_breaker(
    agent_type: str,
    scope: str,
    **kwargs
) -> CircuitBreaker:
    """Create a circuit breaker specifically for WHERE clause operations."""
    name = f"where_clause_{agent_type}_{scope}"
    
    config = CircuitBreakerConfig(
        name=name,
        failure_threshold=kwargs.get('failure_threshold', 3),  # Stricter for WHERE clauses
        recovery_timeout=kwargs.get('recovery_timeout', 30.0),  # Faster recovery
        success_threshold=kwargs.get('success_threshold', 2),
        timeout=kwargs.get('timeout', 10.0),  # Shorter timeout for WHERE clauses
        expected_exception=(Exception,),
        **{k: v for k, v in kwargs.items() if k not in [
            'failure_threshold', 'recovery_timeout', 'success_threshold', 'timeout'
        ]}
    )
    
    breaker = CircuitBreaker(config)
    register_circuit_breaker(name, breaker)
    return breaker