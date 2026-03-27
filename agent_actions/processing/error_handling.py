"""Standardized error handling mixin for processors."""

import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar
from xml.etree import ElementTree as ET

import yaml

from agent_actions.errors import ProcessingError, get_error_detail
from agent_actions.errors.base import AgentActionsError
from agent_actions.logging import fire_event
from agent_actions.logging.events.validation_events import (
    DataLoadingErrorEvent,
    DataParsingErrorEvent,
)

T = TypeVar("T", bound=AgentActionsError)


_PARSE_ERROR_MAP = {
    json.JSONDecodeError: "json",
    yaml.YAMLError: "yaml",
    ET.ParseError: "xml",
    csv.Error: "csv",
}


class ProcessorErrorHandlerMixin:
    """Mixin providing standardized error handling and logging for processors."""

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
        self, operation: str, file_path: str | Path | None = None, **kwargs
    ) -> dict[str, Any]:
        """Build contextual information for error logging."""
        context = {
            "timestamp": datetime.now(UTC).isoformat(),
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
        error_type: type[T] | None = None,
        reraise: bool = True,
        **context_kwargs,
    ) -> None:
        """Log error context and re-raise as the specified error type (or ProcessingError).

        Raises:
            ProcessingError: Or the specified ``error_type`` if ``reraise`` is True.
        """
        context = self.get_error_context(operation, **context_kwargs)
        context["error_type"] = error.__class__.__name__
        context["error_message"] = get_error_detail(error)

        file_path = str(context_kwargs.get("file_path", "unknown"))

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
        file_path: str | Path | None = None,
        **context_kwargs,
    ) -> None:
        """Handle a validation error.

        Raises:
            ValidationError: Always re-raised with contextual message.
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
        self, error: Exception, operation: str, file_path: str | Path, **context_kwargs
    ) -> None:
        """Handle a file operation error.

        Raises:
            FileLoadError: For read/load/open operations.
            FileWriteError: For write/save/create operations.
        """
        from agent_actions.errors import FileLoadError, FileWriteError

        error_type: type[AgentActionsError] | None
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
        """Handle a data transformation error.

        Raises:
            TransformationError: Always re-raised with contextual message.
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
