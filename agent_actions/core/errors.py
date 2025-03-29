"""
Core error handling framework for Agent Actions.

This module provides standardized error classes and handling utilities
for the entire codebase.
"""
import logging
import os
import sys
import traceback
from typing import Any, Callable, Optional, Type, TypeVar, Union, cast

# Configure logger
logger = logging.getLogger(__name__)

# Environment configuration
ENVIRONMENT = os.environ.get("AGENT_ENV", "production")

# Type definitions
T = TypeVar('T')
F = TypeVar('F', bound=Callable[..., Any])


class AgentBaseError(Exception):
    """Base exception class for all agent actions errors."""
    
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.original_error = original_error
        self.message = message
    
    def __str__(self) -> str:
        if self.original_error:
            return f"{self.message} (Original error: {self.original_error})"
        return self.message


# Domain-specific exceptions - extend as needed for your application
class ValidationError(AgentBaseError):
    """Raised when input validation fails."""
    pass


class ProcessingError(AgentBaseError):
    """Raised when content processing or data transformation fails."""
    pass


class ResourceNotFoundError(AgentBaseError):
    """Raised when a requested resource cannot be found."""
    pass


class ConfigurationError(AgentBaseError):
    """Raised when configuration is missing or invalid."""
    pass


class ExternalServiceError(AgentBaseError):
    """Raised when an external service call fails."""
    pass


# Error handling utilities
def handle_errors(
    error_types: Union[Type[Exception], tuple[Type[Exception], ...]] = Exception,
    fallback_value: Optional[Any] = None,
    log_level: int = logging.ERROR,
    reraise: bool = False,
    error_handler: Optional[Callable[[Exception], Any]] = None
) -> Callable[[F], F]:
    """
    Decorator for handling errors in functions.
    
    Args:
        error_types: Exception class(es) to catch
        fallback_value: Value to return if an error occurs
        log_level: Logging level for errors
        reraise: Whether to reraise the error after handling
        error_handler: Custom function to handle the error
        
    Returns:
        Decorated function
    """
    def decorator(func: F) -> F:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except error_types as error:
                # Log the error
                if log_level:
                    logger.log(log_level, f"Error in {func.__name__}: {error}")
                    if log_level >= logging.ERROR:
                        logger.log(log_level, traceback.format_exc())
                
                # Custom error handling
                if error_handler:
                    return error_handler(error)
                
                # Reraise or return fallback
                if reraise:
                    raise
                return fallback_value
        
        return cast(F, wrapper)
    
    return decorator


# Top-level error handler
def configure_global_exception_handler() -> None:
    """
    Configure the global exception handler for the application.
    This should be called at the application's entry point.
    """
    def global_exception_handler(exctype, value, tb):
        """Handle uncaught exceptions at the application level."""
        if ENVIRONMENT == "development":
            # In development, show the full traceback
            sys.__excepthook__(exctype, value, tb)
        else:
            # In production, log the error and show a user-friendly message
            logger.critical(
                "Unhandled exception: %s",
                value,
                exc_info=(exctype, value, tb)
            )
            print("An unexpected error occurred. Please check the logs for details.")
    
    sys.excepthook = global_exception_handler 