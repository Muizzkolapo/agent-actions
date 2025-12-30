"""
Standardized error handling mixin for processors.

This module provides a mixin class that implements consistent error handling
patterns across all processor modules.
"""

# pylint: disable=line-too-long,import-outside-toplevel,no-else-raise
# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
# Line-too-long: Error messages need to be descriptive
# Import-outside-toplevel: Avoid circular imports with error module
# No-else-raise: Code clarity - explicit error handling paths
# Too-many-arguments: Error context requires all these parameters
# Unused-argument: Interface consistency
import json
import logging
import time
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Type, TypeVar, Union
from agent_actions.errors import ProcessingError as ProcessorError  # New modular pattern!

T = TypeVar("T", bound=ProcessorError)


class ProcessorErrorHandlerMixin:
    """
    Mixin class providing standardized error handling for processors.

    This mixin should be inherited by all processor classes to ensure
    consistent error handling and logging across the application.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the mixin with a logger if not already present."""
        super().__init__(*args, **kwargs)
        if not hasattr(self, "logger"):
            self.logger = logging.getLogger(self.__class__.__module__)

    def get_error_context(
        self, operation: str, file_path: Optional[Union[str, Path]] = None, **kwargs
    ) -> Dict[str, Any]:
        """
        Build contextual information for error logging.

        Args:
            operation: The operation that was being performed
            file_path: Optional file path involved in the operation
            **kwargs: Additional context to include

        Returns:
            Dictionary containing error context
        """
        context = {
            "timestamp": datetime.utcnow().isoformat(),
            "processor": self.__class__.__name__,
            "operation": operation,
        }
        if file_path:
            context["file_path"] = str(file_path)
        if hasattr(self, "agent_name"):
            context["agent_name"] = self.agent_name
        if hasattr(self, "agent_config"):
            context["agent_type"] = self.agent_config.get("type", "unknown")
        context.update(kwargs)
        return context

    def handle_processing_error(
        self,
        error: Exception,
        operation: str,
        error_type: Optional[Type[T]] = None,
        reraise: bool = True,
        **context_kwargs,
    ) -> None:
        """
        Handle a processing error with consistent logging and re-raising.

        Args:
            error: The original exception
            operation: Description of the operation that failed
            error_type: Optional specific error type to raise
            reraise: Whether to re-raise the exception (default: True)
            **context_kwargs: Additional context to log

        Raises:
            The specified error type or ProcessorError if not specified
        """
        context = self.get_error_context(operation, **context_kwargs)
        context["error_type"] = error.__class__.__name__
        context["error_message"] = str(error)
        log_entry = {
            "level": "ERROR",
            "message": f"{operation} failed: {str(error)}",
            "context": context,
            "traceback": traceback.format_exc(),
        }
        self.logger.error(json.dumps(log_entry, default=str))
        if reraise:
            if error_type:
                raise error_type(f"{operation} failed: {str(error)}") from error
            else:
                raise ProcessorError(f"{operation} failed: {str(error)}") from error

    def handle_validation_error(
        self,
        error: Exception,
        target: str,
        file_path: Optional[Union[str, Path]] = None,
        **context_kwargs,
    ) -> None:
        """
        Handle a validation error.

        Args:
            error: The original exception
            target: What was being validated
            file_path: Optional file path involved
            **context_kwargs: Additional context to log

        Raises:
            ValidationError with appropriate message
        """
        from agent_actions.errors import ValidationError  # New modular pattern!

        self.handle_processing_error(
            error,
            f"Validation of {target}",
            ValidationError,
            file_path=file_path,
            validation_target=target,
            **context_kwargs,
        )

    def handle_file_error(
        self, error: Exception, operation: str, file_path: Union[str, Path], **context_kwargs
    ) -> None:
        """
        Handle a file operation error.

        Args:
            error: The original exception
            operation: The file operation that failed (e.g., 'read', 'write')
            file_path: Path to the file
            **context_kwargs: Additional context to log

        Raises:
            FileLoadError or FileWriteError depending on operation
        """
        from agent_actions.errors import FileLoadError, FileWriteError  # New modular pattern!

        if operation.lower() in ["read", "load", "open"]:
            error_type = FileLoadError
        elif operation.lower() in ["write", "save", "create"]:
            error_type = FileWriteError
        else:
            error_type = None
        self.handle_processing_error(
            error,
            f"File {operation}",
            error_type,
            file_path=file_path,
            file_operation=operation,
            **context_kwargs,
        )

    def handle_transformation_error(
        self, error: Exception, source_type: str, target_type: str, **context_kwargs
    ) -> None:
        """
        Handle a data transformation error.

        Args:
            error: The original exception
            source_type: Type of source data
            target_type: Type of target data
            **context_kwargs: Additional context to log

        Raises:
            TransformationError with appropriate message
        """
        from agent_actions.errors import TransformationError  # New modular pattern!

        self.handle_processing_error(
            error,
            f"Transformation from {source_type} to {target_type}",
            TransformationError,
            source_type=source_type,
            target_type=target_type,
            **context_kwargs,
        )

    def log_warning(self, message: str, operation: str, **context_kwargs) -> None:
        """
        Log a warning with consistent structure.

        Args:
            message: Warning message
            operation: Operation that generated the warning
            **context_kwargs: Additional context to log
        """
        context = self.get_error_context(operation, **context_kwargs)
        log_entry = {"level": "WARNING", "message": message, "context": context}
        self.logger.warning(json.dumps(log_entry, default=str))

    def log_info(self, message: str, operation: str, **context_kwargs) -> None:
        """
        Log an info message with consistent structure.

        Args:
            message: Info message
            operation: Operation being performed
            **context_kwargs: Additional context to log
        """
        context = self.get_error_context(operation, **context_kwargs)
        log_entry = {"level": "INFO", "message": message, "context": context}
        self.logger.info(json.dumps(log_entry, default=str))

    def with_retry(
        self,
        max_attempts: int = 3,
        delay: float = 1.0,
        backoff: float = 2.0,
        max_delay: float = 60.0,
        exceptions: tuple = (IOError, OSError, ConnectionError),
    ) -> Callable:
        """
        Decorator for adding retry logic to methods.

        DEPRECATED: Use agent_actions.utilities.retry.retry instead.

        Args:
            max_attempts: Maximum number of retry attempts
            delay: Initial delay between retries in seconds
            backoff: Multiplier for delay after each retry
            max_delay: Maximum delay between retries (prevents unbounded backoff)
            exceptions: Tuple of exceptions to catch and retry

        Returns:
            Decorated function with retry logic
        """
        import warnings

        warnings.warn(
            "ProcessorErrorHandlerMixin.with_retry is deprecated. Use agent_actions.utilities.retry.retry instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                last_exception = None
                current_delay = delay
                for attempt in range(max_attempts):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        if attempt < max_attempts - 1:
                            # Log retry attempt with configuration and wait time
                            self.logger.warning(
                                "Retry attempt %s/%s after failure",
                                attempt + 1,
                                max_attempts,
                                extra={
                                    "operation": "retry_attempt",
                                    "function": func.__name__,
                                    "attempt": attempt + 1,
                                    "max_attempts": max_attempts,
                                    "wait_time": current_delay,
                                    "backoff_multiplier": backoff,
                                    "max_delay": max_delay,
                                    "error": str(e),
                                    "error_type": type(e).__name__,
                                },
                            )
                            time.sleep(current_delay)
                            current_delay = min(current_delay * backoff, max_delay)
                        else:
                            # Log final failure after all retries exhausted
                            self.logger.error(
                                "All retry attempts exhausted for %s",
                                func.__name__,
                                extra={
                                    "operation": "retry_exhausted",
                                    "function": func.__name__,
                                    "total_attempts": max_attempts,
                                    "final_error": str(e),
                                    "error_type": type(e).__name__,
                                },
                            )
                if last_exception:
                    raise last_exception
                return None  # Unreachable, but satisfies pylint

            return wrapper

        return decorator

    def with_fallback(
        self,
        fallback_value: Any = None,
        fallback_func: Optional[Callable] = None,
        exceptions: tuple = (Exception,),
        log_fallback: bool = True,
    ) -> Callable:
        """
        Decorator for adding fallback behavior to methods.

        Args:
            fallback_value: Value to return on failure
            fallback_func: Function to call on failure (takes the exception as argument)
            exceptions: Tuple of exceptions to catch
            log_fallback: Whether to log when fallback is used

        Returns:
            Decorated function with fallback logic
        """

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if log_fallback:
                        self.log_warning(
                            f"Using fallback for {func.__name__}",
                            f"{func.__name__} (fallback)",
                            error=str(e),
                            fallback_used=True,
                        )
                    if fallback_func:
                        return fallback_func(e)
                    return fallback_value

            return wrapper

        return decorator

    def handle_partial_failure(
        self, results: list, errors: list, operation: str, threshold: float = 0.5
    ) -> tuple[list, list]:
        """
        Handle partial failures in batch operations.

        Args:
            results: List of successful results
            errors: List of errors encountered
            operation: Description of the batch operation
            threshold: Failure threshold (0.0 to 1.0) above which to raise an error

        Returns:
            Tuple of (successful_results, failed_items)

        Raises:
            ProcessorError if failure rate exceeds threshold
        """
        total_items = len(results) + len(errors)
        failure_rate = len(errors) / total_items if total_items > 0 else 0
        self.log_info(
            f"Batch operation completed with {len(results)} successes and {len(errors)} failures",
            operation,
            total_items=total_items,
            successful=len(results),
            failed=len(errors),
            failure_rate=failure_rate,
        )
        if failure_rate > threshold:
            error_summary = {
                "operation": operation,
                "total_items": total_items,
                "failed_items": len(errors),
                "failure_rate": failure_rate,
                "threshold": threshold,
                "sample_errors": [str(e) for e in errors[:5]],
            }
            raise ProcessorError(
                f"Batch operation '{operation}' exceeded failure threshold: {failure_rate:.2%} > {threshold:.2%}. Failed: {len(errors)}/{total_items} items. Details: {json.dumps(error_summary)}"
            )
        return (results, errors)

    def create_error_recovery_state(
        self, operation: str, state_data: Dict[str, Any], error: Exception
    ) -> Dict[str, Any]:
        """
        Create a recovery state that can be used to resume operations.

        Args:
            operation: The operation that failed
            state_data: Current state data
            error: The error that occurred

        Returns:
            Recovery state dictionary
        """
        recovery_state = {
            "timestamp": datetime.utcnow().isoformat(),
            "operation": operation,
            "processor": self.__class__.__name__,
            "error": {
                "type": error.__class__.__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
            "state": state_data,
            "recovery_instructions": self._get_recovery_instructions(operation, error),
        }
        self.log_info(
            "Created recovery state for failed operation",
            operation,
            recovery_state_id=id(recovery_state),
            can_resume=True,
        )
        return recovery_state

    def _get_recovery_instructions(self, operation: str, error: Exception) -> Dict[str, Any]:
        """
        Generate recovery instructions based on the operation and error type.

        Args:
            operation: The operation that failed
            error: The error that occurred

        Returns:
            Recovery instructions
        """
        instructions = {"can_retry": True, "suggested_action": "retry", "cleanup_required": False}
        if isinstance(error, (IOError, OSError)):
            instructions["suggested_action"] = "check_file_permissions_and_retry"
            instructions["cleanup_required"] = True
        elif isinstance(error, MemoryError):
            instructions["suggested_action"] = "reduce_batch_size_and_retry"
            instructions["can_retry"] = True
        elif isinstance(error, KeyboardInterrupt):
            instructions["suggested_action"] = "resume_from_checkpoint"
            instructions["can_retry"] = True

        return instructions
