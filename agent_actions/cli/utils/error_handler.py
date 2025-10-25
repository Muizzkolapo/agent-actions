"""
Error handling utilities.

This module provides common utilities for handling errors in a consistent way.
"""
import logging
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar, Union
from agent_actions.shared.exceptions import AgentActionsException
logger = logging.getLogger(__name__)
T = TypeVar('T', bound=AgentActionsException)

class ErrorHandler:
    """Utility class for handling errors in a consistent way."""

    @staticmethod
    def format_for_user(error: Exception, context: Optional[Dict[str, Any]]=None) -> str:
        """
        Format error using user-friendly system.

        Args:
            error: The exception to format
            context: Optional context dict

        Returns:
            User-friendly formatted error message
        """
        from agent_actions.core.user_errors import format_user_error
        return format_user_error(error, context)

    @staticmethod
    def handle_error(error: Exception, message: str, error_type: Optional[Type[T]]=None, context: Optional[Dict[str, Any]]=None) -> None:
        """
        Handle an error by logging it and raising an appropriate exception.

        Args:
            error: The original exception.
            message: Error message to use.
            error_type: Optional type of exception to raise.
            context: Optional additional context to log.

        Raises:
            The specified error type or AgentActionsException if not specified.
        """
        error_details = {'error': str(error), 'traceback': traceback.format_exc(), **(context or {})}
        logger.error(message, extra=error_details, exc_info=True)
        if error_type:
            raise error_type(f'{message}: {str(error)}', context=context, cause=error)
        else:
            raise AgentActionsException(f'{message}: {str(error)}', context=context, cause=error)

    @staticmethod
    def handle_validation_error(error: Exception, target: str, context: Optional[Dict[str, Any]]=None) -> None:
        """
        Handle a validation error.

        Args:
            error: The original exception.
            target: Name of the target being validated.
            context: Optional additional context to log.

        Raises:
            ValidationError: With appropriate message.
        """
        from agent_actions.shared.exceptions import ValidationError
        message = f'Validation failed for {target}'
        ErrorHandler.handle_error(error, message, ValidationError, context)

    @staticmethod
    def handle_file_error(error: Exception, operation: str, path: Union[str, Path], context: Optional[Dict[str, Any]]=None) -> None:
        """
        Handle a file operation error.

        Args:
            error: The original exception.
            operation: Name of the operation that failed.
            path: Path being operated on.
            context: Optional additional context to log.

        Raises:
            FileLoadError or FileSystemError: With appropriate message.
        """
        from agent_actions.shared.exceptions import FileLoadError, FileSystemError
        if isinstance(error, (FileNotFoundError, IOError, OSError)):
            if not error.args or 'No such file' in str(error):
                error_type = FileLoadError
            else:
                error_type = FileSystemError
        else:
            error_type = None
        message = f"File operation '{operation}' failed for path: {path}"
        ErrorHandler.handle_error(error, message, error_type, context)

    @staticmethod
    def handle_config_error(error: Exception, operation: str, config_name: str, context: Optional[Dict[str, Any]]=None) -> None:
        """
        Handle a configuration error.

        Args:
            error: The original exception.
            operation: Name of the operation that failed.
            config_name: Name of the configuration.
            context: Optional additional context to log.

        Raises:
            ConfigurationError: With appropriate message.
        """
        from agent_actions.shared.exceptions import ConfigurationError
        message = f"Configuration operation '{operation}' failed for {config_name}"
        ErrorHandler.handle_error(error, message, ConfigurationError, context)

    @staticmethod
    def handle_template_error(error: Exception, operation: str, template_name: str, context: Optional[Dict[str, Any]]=None) -> None:
        """
        Handle a template rendering error.

        Args:
            error: The original exception.
            operation: Name of the operation that failed.
            template_name: Name of the template.
            context: Optional additional context to log.

        Raises:
            TemplateRenderingError: With appropriate message.
        """
        from agent_actions.shared.exceptions import TemplateRenderingError
        message = f"Template operation '{operation}' failed for {template_name}"
        ErrorHandler.handle_error(error, message, TemplateRenderingError, context)

    @staticmethod
    def handle_execution_error(error: Exception, operation: str, target: str, context: Optional[Dict[str, Any]]=None) -> None:
        """
        Handle an execution error.

        Args:
            error: The original exception.
            operation: Name of the operation that failed.
            target: Name of the target being executed.
            context: Optional additional context to log.

        Raises:
            AgentExecutionError: With appropriate message.
        """
        from agent_actions.shared.exceptions import AgentExecutionError
        message = f"Execution of '{operation}' failed for {target}"
        ErrorHandler.handle_error(error, message, AgentExecutionError, context)