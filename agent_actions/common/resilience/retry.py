"""Retry implementation."""

from typing import Callable, Any
import functools


def where_clause_retry(agent_type: str, operation: str, max_attempts: int = 3):
    """WHERE clause retry decorator - simplified implementation."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Simplified implementation - just call the function
            return func(*args, **kwargs)
        return wrapper
    return decorator