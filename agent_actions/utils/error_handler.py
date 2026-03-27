"""Common error handling utilities for consistent error wrapping and logging."""

import logging
from pathlib import Path
from typing import Any, NoReturn, TypeVar

from agent_actions.errors import (
    AgentActionsError,
    AgentExecutionError,
    ConfigurationError,
    FileLoadError,
    FileSystemError,
    TemplateRenderingError,
    ValidationError,
    get_error_detail,
)

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=AgentActionsError)


class ErrorHandler:
    """Utility class for handling errors in a consistent way."""

    @staticmethod
    def format_for_user(error: Exception, context: dict[str, Any] | None = None) -> str:
        """Format an error into a user-friendly message."""
        from agent_actions.logging.errors import format_user_error

        return format_user_error(error, context)

    @staticmethod
    def handle_error(
        error: Exception,
        message: str,
        error_type: type[T] | None = None,
        context: dict[str, Any] | None = None,
    ) -> NoReturn:
        """Log and re-raise as *error_type* (or AgentActionsError)."""
        error_details = {"error": get_error_detail(error), **(context or {})}
        # DEBUG only; the top-level handler (main.py) logs at ERROR
        logger.debug("%s: %s", message, get_error_detail(error), extra=error_details)
        if error_type:
            raise error_type(f"{message}: {get_error_detail(error)}", context=context, cause=error)

        raise AgentActionsError(
            f"{message}: {get_error_detail(error)}", context=context, cause=error
        )

    @staticmethod
    def handle_validation_error(
        error: Exception, target: str, context: dict[str, Any] | None = None
    ) -> NoReturn:
        """Re-raise as ValidationError for the given *target*."""
        message = f"Validation failed for {target}"
        ErrorHandler.handle_error(error, message, ValidationError, context)

    @staticmethod
    def handle_file_error(
        error: Exception,
        operation: str,
        path: str | Path,
        context: dict[str, Any] | None = None,
    ) -> NoReturn:
        """Re-raise as FileLoadError or FileSystemError."""

        error_type: type[FileSystemError]
        if isinstance(error, FileNotFoundError):
            error_type = FileLoadError
        elif isinstance(error, OSError):
            error_type = FileSystemError
        else:
            error_type = FileSystemError
        message = f"File operation '{operation}' failed for path: {path}"
        ErrorHandler.handle_error(error, message, error_type, context)

    @staticmethod
    def handle_config_error(
        error: Exception, operation: str, config_name: str, context: dict[str, Any] | None = None
    ) -> NoReturn:
        """Re-raise as ConfigurationError for the given *config_name*."""

        message = f"Configuration operation '{operation}' failed for {config_name}"
        ErrorHandler.handle_error(error, message, ConfigurationError, context)

    @staticmethod
    def handle_template_error(
        error: Exception,
        operation: str,
        template_name: str,
        context: dict[str, Any] | None = None,
    ) -> NoReturn:
        """Re-raise as TemplateRenderingError for the given *template_name*."""

        message = f"Template operation '{operation}' failed for {template_name}"
        ErrorHandler.handle_error(error, message, TemplateRenderingError, context)

    @staticmethod
    def handle_execution_error(
        error: Exception, operation: str, target: str, context: dict[str, Any] | None = None
    ) -> NoReturn:
        """Re-raise as AgentExecutionError for the given *target*."""

        message = f"Execution of '{operation}' failed for {target}"
        ErrorHandler.handle_error(error, message, AgentExecutionError, context)
