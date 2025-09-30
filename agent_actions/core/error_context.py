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

            # Extract all parameters from function arguments
            try:
                sig = inspect.signature(func)
                bound_args = sig.bind(*args, **kwargs)
                bound_args.apply_defaults()

                # Extract all parameters (excluding 'self' and 'cls' for methods)
                for param_name, value in bound_args.arguments.items():
                    # Skip self/cls for methods
                    if param_name in ('self', 'cls'):
                        continue

                    # If this is a **kwargs parameter, unpack it into context
                    param = sig.parameters.get(param_name)
                    if param and param.kind == inspect.Parameter.VAR_KEYWORD:
                        # Unpack **kwargs into context
                        if isinstance(value, dict):
                            for k, v in value.items():
                                if v is not None and v != "":
                                    if isinstance(v, (str, int, float, bool, type(None))):
                                        context[k] = v
                                    elif isinstance(v, (list, tuple, dict, set)):
                                        context[k] = v
                                    else:
                                        context[k] = str(v)[:100]
                        continue

                    # Only include non-None, non-empty values
                    if value is not None and value != "":
                        # For simple types, include directly
                        if isinstance(value, (str, int, float, bool, type(None))):
                            context[param_name] = value
                        # For collections, include up to a reasonable size
                        elif isinstance(value, (list, tuple, dict, set)):
                            context[param_name] = value
                        # For complex objects, include string representation
                        else:
                            context[param_name] = str(value)[:100]  # Truncate long objects

            except Exception as e:
                # If context extraction fails, log it but don't break the function
                logger.debug(f"Failed to extract context from {func.__name__}: {e}")

            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Attach context to the exception
                if not hasattr(e, 'context'):
                    e.context = {}
                # Only add keys that don't already exist (inner decorators take precedence)
                for key, value in context.items():
                    if key not in e.context:
                        e.context[key] = value
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


def with_command_context(command: str):
    """
    Shorthand decorator for command operations.

    Args:
        command: The command name (e.g., "init", "run", "render")

    Usage:
        @with_command_context("init")
        def initialize_project(project_name):
            # Command logic
            pass
    """
    return with_error_context(command=command, resource_type="command")


def get_context_from_exception(exc: Exception) -> Dict[str, Any]:
    """
    Extract error context from an exception.

    Args:
        exc: Exception to extract context from

    Returns:
        Dictionary of context information, empty if no context found
    """
    return getattr(exc, 'context', {})


def add_context_to_exception(exc: Exception, context: Dict[str, Any]) -> None:
    """
    Add context to an existing exception.

    Args:
        exc: Exception to add context to
        context: Context dictionary to add
    """
    if not hasattr(exc, 'context'):
        exc.context = {}
    exc.context.update(context)