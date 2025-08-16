"""
Production-grade retry mechanisms with exponential backoff and jitter.
Provides resilient retry patterns for WHERE clause operations.
"""
import time
import random
import asyncio
import functools
from typing import Callable, Any, Optional, Union, Type, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

from ..monitoring.metrics import get_metrics_collector
from ..monitoring.logging import get_logger

logger = logging.getLogger(__name__)


class BackoffStrategy(Enum):
    """Backoff strategies for retries."""
    FIXED = "fixed"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    EXPONENTIAL_JITTER = "exponential_jitter"


@dataclass
class RetryConfig:
    """Configuration for retry mechanism."""
    max_attempts: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    backoff_strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL_JITTER
    jitter_factor: float = 0.1  # 10% jitter
    exponential_base: float = 2.0
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)
    non_retryable_exceptions: Tuple[Type[Exception], ...] = ()
    retry_condition: Optional[Callable[[Exception], bool]] = None
    name: str = "default"


class RetryExhaustedError(Exception):
    """Exception raised when all retry attempts are exhausted."""
    
    def __init__(self, attempts: int, last_exception: Exception):
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(
            f"Retry exhausted after {attempts} attempts. "
            f"Last exception: {type(last_exception).__name__}: {last_exception}"
        )


class Retry:
    """
    Production-grade retry mechanism with comprehensive monitoring.
    """
    
    def __init__(self, config: RetryConfig):
        self.config = config
        self.metrics = get_metrics_collector()
        self.structured_logger = get_logger()
    
    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for the given attempt number."""
        if self.config.backoff_strategy == BackoffStrategy.FIXED:
            delay = self.config.base_delay
        
        elif self.config.backoff_strategy == BackoffStrategy.LINEAR:
            delay = self.config.base_delay * attempt
        
        elif self.config.backoff_strategy == BackoffStrategy.EXPONENTIAL:
            delay = self.config.base_delay * (self.config.exponential_base ** (attempt - 1))
        
        elif self.config.backoff_strategy == BackoffStrategy.EXPONENTIAL_JITTER:
            exponential_delay = self.config.base_delay * (self.config.exponential_base ** (attempt - 1))
            jitter = exponential_delay * self.config.jitter_factor * (2 * random.random() - 1)
            delay = exponential_delay + jitter
        
        else:
            delay = self.config.base_delay
        
        # Cap at max_delay
        return min(delay, self.config.max_delay)
    
    def _should_retry(self, exception: Exception, attempt: int) -> bool:
        """Determine if we should retry based on the exception and attempt count."""
        # Check attempt count
        if attempt >= self.config.max_attempts:
            return False
        
        # Check non-retryable exceptions first
        if isinstance(exception, self.config.non_retryable_exceptions):
            return False
        
        # Check retryable exceptions
        if not isinstance(exception, self.config.retryable_exceptions):
            return False
        
        # Check custom retry condition
        if self.config.retry_condition:
            return self.config.retry_condition(exception)
        
        return True
    
    def _log_retry_attempt(self, attempt: int, exception: Exception, delay: float):
        """Log retry attempt with structured logging."""
        self.structured_logger.warning(
            f"Retry attempt {attempt} for {self.config.name}",
            context={'component': 'retry', 'operation': 'retry_attempt'},
            error_details={
                'attempt': attempt,
                'max_attempts': self.config.max_attempts,
                'exception_type': type(exception).__name__,
                'exception_message': str(exception),
                'delay_seconds': delay,
                'backoff_strategy': self.config.backoff_strategy.value
            }
        )
    
    def _log_retry_exhausted(self, total_attempts: int, last_exception: Exception, total_time: float):
        """Log when retries are exhausted."""
        self.structured_logger.error(
            f"Retry exhausted for {self.config.name}",
            context={'component': 'retry', 'operation': 'retry_exhausted'},
            error_details={
                'total_attempts': total_attempts,
                'total_time_seconds': total_time,
                'last_exception_type': type(last_exception).__name__,
                'last_exception_message': str(last_exception),
                'config': {
                    'max_attempts': self.config.max_attempts,
                    'backoff_strategy': self.config.backoff_strategy.value,
                    'base_delay': self.config.base_delay,
                    'max_delay': self.config.max_delay
                }
            }
        )
    
    def _log_retry_success(self, attempt: int, total_time: float):
        """Log successful retry."""
        self.structured_logger.info(
            f"Retry succeeded for {self.config.name} on attempt {attempt}",
            context={'component': 'retry', 'operation': 'retry_success'},
            performance_metrics={
                'attempt': attempt,
                'total_time_seconds': total_time,
                'success_rate': 1.0 / attempt if attempt > 0 else 1.0
            }
        )
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with retry logic.
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            RetryExhaustedError: When all retry attempts fail
        """
        start_time = time.time()
        last_exception = None
        
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                result = func(*args, **kwargs)
                
                # Log success if we had previous failures
                if attempt > 1:
                    total_time = time.time() - start_time
                    self._log_retry_success(attempt, total_time)
                    
                    # Record metrics
                    self.metrics.increment_counter(
                        "retry_success_total",
                        {
                            'retry_name': self.config.name,
                            'attempt': str(attempt)
                        }
                    )
                    self.metrics.observe_histogram(
                        "retry_duration_seconds",
                        {
                            'retry_name': self.config.name,
                            'result': 'success'
                        },
                        total_time
                    )
                
                return result
            
            except Exception as e:
                last_exception = e
                
                # Record failed attempt metrics
                self.metrics.increment_counter(
                    "retry_attempt_total",
                    {
                        'retry_name': self.config.name,
                        'attempt': str(attempt),
                        'exception_type': type(e).__name__
                    }
                )
                
                # Check if we should retry
                if not self._should_retry(e, attempt):
                    break
                
                # Calculate delay and wait
                if attempt < self.config.max_attempts:
                    delay = self._calculate_delay(attempt)
                    self._log_retry_attempt(attempt, e, delay)
                    
                    # Sleep for calculated delay
                    time.sleep(delay)
        
        # All retries exhausted
        total_time = time.time() - start_time
        self._log_retry_exhausted(self.config.max_attempts, last_exception, total_time)
        
        # Record final failure metrics
        self.metrics.increment_counter(
            "retry_exhausted_total",
            {
                'retry_name': self.config.name,
                'final_exception_type': type(last_exception).__name__
            }
        )
        self.metrics.observe_histogram(
            "retry_duration_seconds",
            {
                'retry_name': self.config.name,
                'result': 'failure'
            },
            total_time
        )
        
        raise RetryExhaustedError(self.config.max_attempts, last_exception)
    
    async def acall(self, func: Callable, *args, **kwargs) -> Any:
        """
        Async version of call method.
        """
        start_time = time.time()
        last_exception = None
        
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    # Run sync function in executor
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, func, *args, **kwargs)
                
                # Log success if we had previous failures
                if attempt > 1:
                    total_time = time.time() - start_time
                    self._log_retry_success(attempt, total_time)
                    
                    # Record metrics
                    self.metrics.increment_counter(
                        "retry_success_total",
                        {
                            'retry_name': self.config.name,
                            'attempt': str(attempt)
                        }
                    )
                
                return result
            
            except Exception as e:
                last_exception = e
                
                # Record failed attempt metrics
                self.metrics.increment_counter(
                    "retry_attempt_total",
                    {
                        'retry_name': self.config.name,
                        'attempt': str(attempt),
                        'exception_type': type(e).__name__
                    }
                )
                
                # Check if we should retry
                if not self._should_retry(e, attempt):
                    break
                
                # Calculate delay and wait
                if attempt < self.config.max_attempts:
                    delay = self._calculate_delay(attempt)
                    self._log_retry_attempt(attempt, e, delay)
                    
                    # Async sleep
                    await asyncio.sleep(delay)
        
        # All retries exhausted
        total_time = time.time() - start_time
        self._log_retry_exhausted(self.config.max_attempts, last_exception, total_time)
        
        # Record final failure metrics
        self.metrics.increment_counter(
            "retry_exhausted_total",
            {
                'retry_name': self.config.name,
                'final_exception_type': type(last_exception).__name__
            }
        )
        
        raise RetryExhaustedError(self.config.max_attempts, last_exception)


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL_JITTER,
    jitter_factor: float = 0.1,
    exponential_base: float = 2.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    non_retryable_exceptions: Tuple[Type[Exception], ...] = (),
    retry_condition: Optional[Callable[[Exception], bool]] = None,
    name: Optional[str] = None
):
    """
    Decorator to add retry functionality to a function.
    
    Args:
        max_attempts: Maximum number of retry attempts
        base_delay: Base delay between retries in seconds
        max_delay: Maximum delay between retries
        backoff_strategy: Strategy for calculating retry delays
        jitter_factor: Factor for adding jitter to delays
        exponential_base: Base for exponential backoff
        retryable_exceptions: Exceptions that should trigger retries
        non_retryable_exceptions: Exceptions that should not trigger retries
        retry_condition: Custom function to determine if retry should happen
        name: Name for metrics and logging
    """
    def decorator(func: Callable) -> Callable:
        retry_name = name or f"{func.__module__}.{func.__name__}"
        config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            backoff_strategy=backoff_strategy,
            jitter_factor=jitter_factor,
            exponential_base=exponential_base,
            retryable_exceptions=retryable_exceptions,
            non_retryable_exceptions=non_retryable_exceptions,
            retry_condition=retry_condition,
            name=retry_name
        )
        retry_instance = Retry(config)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return retry_instance.call(func, *args, **kwargs)
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await retry_instance.acall(func, *args, **kwargs)
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            async_wrapper._retry = retry_instance
            return async_wrapper
        else:
            wrapper._retry = retry_instance
            return wrapper
    
    return decorator


# Specific retry configurations for WHERE clause operations
def where_clause_retry(
    agent_type: str,
    scope: str,
    max_attempts: int = 2,  # Conservative for WHERE clauses
    base_delay: float = 0.1,  # Fast retry for WHERE clauses
    **kwargs
):
    """
    Specialized retry decorator for WHERE clause operations.
    """
    # Security-related exceptions should not be retried
    security_exceptions = (
        ValueError,  # Often indicates malicious input
        SyntaxError,  # Code injection attempts
        NameError,   # Variable injection attempts
    )
    
    # Performance-related exceptions might be retryable
    retryable_exceptions = (
        TimeoutError,
        ConnectionError,
        # Add other transient exceptions
    )
    
    return retry(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=kwargs.get('max_delay', 2.0),  # Short max delay for WHERE clauses
        backoff_strategy=BackoffStrategy.EXPONENTIAL_JITTER,
        retryable_exceptions=kwargs.get('retryable_exceptions', retryable_exceptions),
        non_retryable_exceptions=kwargs.get('non_retryable_exceptions', security_exceptions),
        name=f"where_clause_{agent_type}_{scope}",
        **{k: v for k, v in kwargs.items() if k not in [
            'max_delay', 'retryable_exceptions', 'non_retryable_exceptions'
        ]}
    )


# Utility functions for common retry patterns
def create_database_retry() -> Retry:
    """Create retry configuration for database operations."""
    config = RetryConfig(
        max_attempts=3,
        base_delay=0.5,
        max_delay=10.0,
        backoff_strategy=BackoffStrategy.EXPONENTIAL_JITTER,
        retryable_exceptions=(ConnectionError, TimeoutError),
        name="database_operation"
    )
    return Retry(config)


def create_network_retry() -> Retry:
    """Create retry configuration for network operations."""
    config = RetryConfig(
        max_attempts=5,
        base_delay=1.0,
        max_delay=30.0,
        backoff_strategy=BackoffStrategy.EXPONENTIAL_JITTER,
        retryable_exceptions=(ConnectionError, TimeoutError),
        name="network_operation"
    )
    return Retry(config)


def create_parsing_retry() -> Retry:
    """Create retry configuration for parsing operations (no retries for security)."""
    config = RetryConfig(
        max_attempts=1,  # No retries for parsing errors
        base_delay=0.0,
        non_retryable_exceptions=(SyntaxError, ValueError, NameError),
        name="parsing_operation"
    )
    return Retry(config)