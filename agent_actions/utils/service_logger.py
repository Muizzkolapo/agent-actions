"""
Service logging utilities.

This module provides common utilities for logging in services.
"""

import logging
from typing import Any, Dict
from pathlib import Path


class ServiceLogger:
    """Utility class for service logging."""

    @staticmethod
    def log_operation_start(
        logger: logging.Logger, operation: str, user_facing: bool = False, **context: Any
    ) -> None:
        """
        Log the start of an operation.

        Args:
            logger: Logger instance to use.
            operation: Name of the operation.
            user_facing: Whether this is a user-facing operation (INFO)
                or internal (DEBUG). Default False.
            **context: Additional context to log.
        """
        log_func = logger.info if user_facing else logger.debug
        log_func(f"Starting {operation}", extra={"operation": operation, **context})

    @staticmethod
    def log_operation_success(
        logger: logging.Logger, operation: str, user_facing: bool = False, **context: Any
    ) -> None:
        """
        Log the successful completion of an operation.

        Args:
            logger: Logger instance to use.
            operation: Name of the operation.
            user_facing: Whether this is a user-facing operation (INFO)
                or internal (DEBUG). Default False.
            **context: Additional context to log.
        """
        log_func = logger.info if user_facing else logger.debug
        log_func(f"Successfully completed {operation}", extra={"operation": operation, **context})

    @staticmethod
    def log_operation_error(
        logger: logging.Logger, operation: str, error: Exception, **context: Any
    ) -> None:
        """
        Log an error that occurred during an operation.

        Args:
            logger: Logger instance to use.
            operation: Name of the operation.
            error: Exception that occurred.
            **context: Additional context to log.
        """
        logger.error(
            f"Failed to {operation}: {str(error)}",
            extra={"operation": operation, "error": str(error), **context},
        )

    @staticmethod
    def log_validation_start(logger: logging.Logger, target: str, **context: Any) -> None:
        """
        Log the start of a validation operation.

        Args:
            logger: Logger instance to use.
            target: Name of the target being validated.
            **context: Additional context to log.
        """
        logger.debug(f"Starting validation of {target}", extra={"target": target, **context})

    @staticmethod
    def log_validation_success(logger: logging.Logger, target: str, **context: Any) -> None:
        """
        Log the successful completion of a validation operation.

        Args:
            logger: Logger instance to use.
            target: Name of the target that was validated.
            **context: Additional context to log.
        """
        logger.debug(f"Successfully validated {target}", extra={"target": target, **context})

    @staticmethod
    def log_validation_error(
        logger: logging.Logger, target: str, error: Exception, **context: Any
    ) -> None:
        """
        Log an error that occurred during validation.

        Args:
            logger: Logger instance to use.
            target: Name of the target being validated.
            error: Exception that occurred.
            **context: Additional context to log.
        """
        logger.error(
            f"Validation of {target} failed: {str(error)}",
            extra={"target": target, "error": str(error), **context},
        )

    @staticmethod
    def log_file_operation(logger: logging.Logger, operation: str, path: Path) -> None:
        """
        Log a file operation.

        Args:
            logger: Logger instance to use.
            operation: Name of the operation.
            path: Path being operated on.
        """
        logger.debug(f"{operation} file: {path}", extra={"operation": operation, "path": str(path)})

    @staticmethod
    def log_config_operation(
        logger: logging.Logger, operation: str, config_data: Dict[str, Any]
    ) -> None:
        """
        Log a configuration operation.

        Args:
            logger: Logger instance to use.
            operation: Name of the operation.
            config_data: Configuration data being operated on.
        """
        logger.debug(
            f"{operation} configuration", extra={"operation": operation, "config_data": config_data}
        )
