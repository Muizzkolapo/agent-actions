"""
Unified retry utility for agent-actions.

This module provides a robust, reusable retry mechanism with exponential backoff,
supporting both synchronous and asynchronous operations.
"""

import asyncio
import time
import logging
import functools
from typing import Type, Tuple, Callable, Union, TypeVar
from dataclasses import dataclass

logger = logging.getLogger(__name__)

T = TypeVar('T')

@dataclass
class RetryStrategy:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    delay: float = 1.0
    backoff: float = 2.0
    max_delay: float = 60.0
    exceptions: Tuple[Type[Exception], ...] = (Exception,)

    def __post_init__(self):
        """Validate configuration."""
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.delay < 0:
            raise ValueError("delay must be non-negative")
        if self.backoff < 1:
            raise ValueError("backoff must be at least 1.0")

def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    max_delay: float = 60.0,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = (Exception,)
) -> Callable:
    """
    Decorator for adding retry logic to functions.
    
    Supports both synchronous and asynchronous functions.
    
    Args:
        max_attempts: Maximum number of attempts
        delay: Initial delay between retries in seconds
        backoff: Multiplier for delay after each retry
        max_delay: Maximum delay in seconds
        exceptions: Exception type or tuple of exceptions to catch
        
    Returns:
        Decorated function
    """
    if not isinstance(exceptions, tuple):
        exceptions = (exceptions,)

    strategy = RetryStrategy(
        max_attempts=max_attempts,
        delay=delay,
        backoff=backoff,
        max_delay=max_delay,
        exceptions=exceptions
    )

    def decorator(func: Callable[..., T]) -> Callable[..., T]:

        # Check if function is a coroutine
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs) -> T:
                last_exception = None
                current_delay = strategy.delay
                # Extract exception tuple for proper except clause
                exception_types = strategy.exceptions

                for attempt in range(1, strategy.max_attempts + 1):
                    try:
                        return await func(*args, **kwargs)
                    except exception_types as e:  # pylint: disable=catching-non-exception
                        last_exception = e
                        if attempt == strategy.max_attempts:
                            logger.warning(
                                "Retry failed after %s attempts for %s: %s",
                                attempt, func.__name__, str(e)
                            )
                            raise

                        logger.debug(
                            "Retry attempt %s/%s for %s after error: %s. Waiting %.2fs",
                            attempt, strategy.max_attempts, func.__name__, str(e), current_delay
                        )

                        await asyncio.sleep(current_delay)
                        current_delay = min(current_delay * strategy.backoff, strategy.max_delay)

                # Should be unreachable due to raise in loop, but for type safety
                if last_exception:
                    raise last_exception
                return None  # type: ignore
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            last_exception = None
            current_delay = strategy.delay
            # Extract exception tuple for proper except clause
            exception_types = strategy.exceptions

            for attempt in range(1, strategy.max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exception_types as e:  # pylint: disable=catching-non-exception
                    last_exception = e
                    if attempt == strategy.max_attempts:
                        logger.warning(
                            "Retry failed after %s attempts for %s: %s",
                            attempt, func.__name__, str(e)
                        )
                        raise

                    logger.debug(
                        "Retry attempt %s/%s for %s after error: %s. Waiting %.2fs",
                        attempt, strategy.max_attempts, func.__name__, str(e), current_delay
                    )

                    time.sleep(current_delay)
                    current_delay = min(current_delay * strategy.backoff, strategy.max_delay)

            if last_exception:
                raise last_exception
            return None  # type: ignore
        return sync_wrapper

    return decorator
