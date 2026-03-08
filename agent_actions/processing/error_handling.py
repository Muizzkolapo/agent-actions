"""
Standardized error handling mixin for processors.

This module provides a mixin class that implements consistent error handling
patterns across all processor modules.
"""

# Line-too-long: Error messages need to be descriptive
# Import-outside-toplevel: Avoid circular imports with error module
# No-else-raise: Code clarity - explicit error handling paths
# Too-many-arguments: Error context requires all these parameters
# Unused-argument: Interface consistency
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar, Union
from xml.etree import ElementTree as ET

import yaml

from agent_actions.errors import ProcessingError
from agent_actions.errors import get_error_detail
from agent_actions.logging import fire_event
from agent_actions.logging.events.types import DataParsingErrorEvent, DataLoadingErrorEvent

T = TypeVar("T", bound=ProcessingError)


_PARSE_ERROR_MAP = {
    json.JSONDecodeError: "json",
    yaml.YAMLError: "yaml",
    ET.ParseError: "xml",
    csv.Error: "csv",
}


class ProcessorErrorHandlerMixin:
    """
    Mixin class providing standardized error handling for processors.

    This mixin should be inherited by all processor classes to ensure
    consistent error handling and logging across the application.
    """

    @property
    def logger(self):
        """Lazy logger avoids MRO __init__ conflicts in mixin chains."""
        if not hasattr(self, "_logger"):
            self._logger = logging.getLogger(self.__class__.__module__)
        return self._logger

    @logger.setter
    def logger(self, value):
        """Allow subclasses to override the logger in __init__."""
        self._logger = value

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
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
            The specified error type or ProcessingError if not specified
        """
        context = self.get_error_context(operation, **context_kwargs)
        context["error_type"] = error.__class__.__name__
        context["error_message"] = get_error_detail(error)

        # Fire appropriate data error event
        file_path = str(context_kwargs.get("file_path", "unknown"))

        # Check if this is a parse error
        format_type = None
        for error_class, fmt in _PARSE_ERROR_MAP.items():
            if isinstance(error, error_class):
                format_type = fmt
                break

        if format_type:
            fire_event(
                DataParsingErrorEvent(
                    file_path=file_path,
                    format=format_type,
                    error=get_error_detail(error),
                )
            )
        else:
            fire_event(
                DataLoadingErrorEvent(
                    file_path=file_path,
                    error=get_error_detail(error),
                )
            )

        if not reraise:
            self.logger.warning(
                "%s failed (not reraising): %s",
                operation,
                get_error_detail(error),
            )
            return

        if error_type:
            raise error_type(f"{operation} failed: {get_error_detail(error)}") from error
        raise ProcessingError(f"{operation} failed: {get_error_detail(error)}") from error

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
        from agent_actions.errors import ValidationError

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
        from agent_actions.errors import FileLoadError, FileWriteError

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
        from agent_actions.errors import TransformationError

        self.handle_processing_error(
            error,
            f"Transformation from {source_type} to {target_type}",
            TransformationError,
            source_type=source_type,
            target_type=target_type,
            **context_kwargs,
        )
