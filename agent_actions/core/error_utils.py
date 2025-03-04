"""
Error handling utilities for Agent Actions.

This module provides decorators and utilities for standardized error handling
across the Agent Actions framework.
"""

import functools
import logging
import sys
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union, cast

from agent_actions.core.exceptions import (
    AgentError,
    UnhandledError,
    CliError,
    ErrorCategory,
    ExitCode,
)

logger = logging.getLogger(__name__)

# Type variables for function annotations
F = TypeVar('F', bound=Callable[..., Any])
T = TypeVar('T')


def handle_errors(
    excluded_types: Optional[List[Type[Exception]]] = None,
    error_category: Optional[ErrorCategory] = None,
    log_level: int = logging.ERROR,
) -> Callable[[F], F]:
    """
    Decorator to handle exceptions in a standardized way.
    
    Args:
        excluded_types: Exception types to let pass through unmodified
        error_category: Category to assign to unhandled errors
        log_level: Logging level for errors
    
    Returns:
        Decorated function
    """
    excluded = excluded_types or []
    
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except tuple(excluded) as e:
                # Let excluded exception types pass through
                raise
            except AgentError as e:
                # Log our custom exceptions
                logger.log(log_level, str(e))
                raise
            except Exception as e:
                # Wrap other exceptions
                category = error_category or ErrorCategory.UNKNOWN
                wrapped = UnhandledError(e, category=category)
                logger.log(log_level, str(wrapped))
                raise wrapped from e
        
        return cast(F, wrapper)
    
    return decorator


def cli_command(func: F) -> F:
    """
    Decorator for CLI commands to handle errors and exit with appropriate code.
    
    Args:
        func: CLI command function to decorate
    
    Returns:
        Decorated function
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except CliError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(e.exit_code.value)
        except AgentError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(e.exit_code.value)
        except Exception as e:
            wrapped = UnhandledError(e)
            print(f"Unhandled error: {wrapped}", file=sys.stderr)
            sys.exit(ExitCode.UNHANDLED_ERROR.value)
    
    return cast(F, wrapper)


def try_operation(
    operation: Callable[[], T],
    error_message: str,
    error_class: Type[AgentError],
    **kwargs: Any
) -> T:
    """
    Execute an operation and raise a specific error type if it fails.
    
    Args:
        operation: Function to execute
        error_message: Message to use if the operation fails
        error_class: Error class to raise on failure
        **kwargs: Additional keyword arguments for the error constructor
    
    Returns:
        Result of the operation function
    
    Raises:
        The specified error type if the operation fails
    """
    try:
        return operation()
    except Exception as e:
        # Include the original error message in the details
        kwargs['original_error'] = str(e)
        
        # For the top-level error message, use the provided message
        # and append the original error
        full_message = f"{error_message}: {str(e)}"
        
        # Create and raise the error
        error = error_class(full_message, **kwargs)
        raise error from e


def with_cleanup(
    cleanup_action: Callable[[], None]
) -> Callable[[F], F]:
    """
    Decorator to add a cleanup step to be executed before raising an error.
    
    Args:
        cleanup_action: Function to execute as a cleanup step
    
    Returns:
        Decorated function
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.info("Executing cleanup step before raising error")
                try:
                    cleanup_action()
                except Exception as cleanup_error:
                    logger.warning(f"Cleanup step failed: {cleanup_error}")
                raise
        
        return cast(F, wrapper)
    
    return decorator