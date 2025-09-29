"""
Error context decorators for automatic context capture.

This module provides decorators that automatically capture function parameters
and attach them to exceptions as context. This helps provide better error
messages without manual context passing.
"""

import inspect
import logging
from functools import wraps
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)


def with_error_context(**context_kwargs):
    """
    Decorator that automatically enriches exceptions with context.

    This decorator captures function parameters and provided context,
    then attaches them to any exceptions that occur during execution.

    Args:
        **context_kwargs: Additional context to attach (e.g., operation="load_config")

    Usage:
        @with_error_context(operation="load_config", resource_type="agent")
        def load_agent_config(agent_name: str):
            # Context is automatically captured if an exception occurs
            pass

    The decorator will automatically extract these common parameters:
    - agent_name
    - file_path
    - config_name
    - model
    - provider

    Example:
        @with_error_context(operation="process", resource_type="agent")
        def process_agent(agent_name: str, config: Dict):
            raise ValueError("Something went wrong")

        # The exception will have error_context:
        # {
        #   'function': 'process_agent',
        #   'module': 'my_module',
        #   'operation': 'process',
        #   'resource_type': 'agent',
        #   'agent_name': 'my-agent'
        # }
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Build context from decorator args and function signature
            context = {
                'function': func.__name__,
                'module': func.__module__,
                **context_kwargs
            }

            # Extract relevant parameters from function arguments
            try:
                sig = inspect.signature(func)
                bound_args = sig.bind(*args, **kwargs)
                bound_args.apply_defaults()

                # Extract commonly used parameters
                relevant_params = [
                    'agent_name', 'file_path', 'config_name',
                    'model', 'provider', 'agent', 'config'
                ]

                for param_name in relevant_params:
                    if param_name in bound_args.arguments:
                        value = bound_args.arguments[param_name]
                        # Only include non-None, non-empty values
                        if value is not None and value != "":
                            # For complex objects, just include their string representation
                            if isinstance(value, (str, int, float, bool)):
                                context[param_name] = value
                            else:
                                context[param_name] = str(value)[:100]  # Truncate long objects

            except Exception as e:
                # If context extraction fails, log it but don't break the function
                logger.debug(f"Failed to extract context from {func.__name__}: {e}")

            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Attach context to the exception
                if not hasattr(e, 'error_context'):
                    e.error_context = {}
                e.error_context.update(context)
                raise

        return wrapper
    return decorator


# Convenience decorators for common use cases

def with_agent_context(func: Callable) -> Callable:
    """
    Shorthand decorator for agent-related operations.

    Equivalent to @with_error_context(operation=func.__name__, resource_type="agent")
    """
    return with_error_context(operation=func.__name__, resource_type="agent")(func)


def with_file_context(func: Callable) -> Callable:
    """
    Shorthand decorator for file operations.

    Equivalent to @with_error_context(operation=func.__name__, resource_type="file")
    """
    return with_error_context(operation=func.__name__, resource_type="file")(func)


def with_api_context(provider: str):
    """
    Shorthand decorator for API operations.

    Args:
        provider: The API provider name (e.g., "anthropic", "openai")

    Usage:
        @with_api_context("anthropic")
        def submit_batch(self, requests):
            # API call logic
            pass
    """
    return with_error_context(operation="api_call", provider=provider)


def with_config_context(func: Callable) -> Callable:
    """
    Shorthand decorator for configuration operations.

    Equivalent to @with_error_context(operation=func.__name__, resource_type="config")
    """
    return with_error_context(operation=func.__name__, resource_type="config")(func)


def get_context_from_exception(exc: Exception) -> Dict[str, Any]:
    """
    Extract error context from an exception.

    Args:
        exc: Exception to extract context from

    Returns:
        Dictionary of context information, empty if no context found
    """
    return getattr(exc, 'error_context', {})


def add_context_to_exception(exc: Exception, context: Dict[str, Any]) -> None:
    """
    Add context to an existing exception.

    Args:
        exc: Exception to add context to
        context: Context dictionary to add
    """
    if not hasattr(exc, 'error_context'):
        exc.error_context = {}
    exc.error_context.update(context)