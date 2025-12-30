"""
Path validation utilities.

This module provides common utilities for validating file and directory paths,
now conforming to the BaseValidator interface.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from agent_actions.cli.utils.service_logger import ServiceLogger
from agent_actions.validation.base_validator import BaseValidator

logger = logging.getLogger(__name__)


@dataclass
class PathValidationOptions:
    """Options for path validation."""

    required: bool = True
    must_be_readable: bool = True
    must_be_writable: bool = False
    must_be_executable: bool = False


class PathValidator(BaseValidator):
    """
    Utility class for validating file and directory paths,
    inheriting from BaseValidator.
    """

    def _validate_path_entity_logic(
        self,
        path_obj: Path,
        entity_type: str,
        entity_name: str,
        options: PathValidationOptions,
    ) -> None:
        """
        Generic logic to validate a path (file or directory) and add errors.
        """
        operation_desc = f"validate {entity_type} '{entity_name}' at {path_obj}"
        ServiceLogger.log_operation_start(logger, operation_desc)
        path_exists = self._ensure_path_exists(path_obj)
        if options.required and not path_exists:
            msg = f"{entity_name} ({entity_type}) does not exist: {path_obj}"
            self.add_error(msg)
            ServiceLogger.log_operation_error(logger, operation_desc, Exception(msg))
            return
        if path_exists:
            if entity_type == "directory":
                if not self._is_directory(path_obj):
                    msg = f"{entity_name} path is not a directory: {path_obj}"
                    self.add_error(msg)
                    ServiceLogger.log_operation_error(logger, operation_desc, Exception(msg))
                    return
            elif entity_type == "file":
                if not self._is_file(path_obj):
                    msg = f"{entity_name} path is not a file: {path_obj}"
                    self.add_error(msg)
                    ServiceLogger.log_operation_error(logger, operation_desc, Exception(msg))
                    return
            else:
                msg = f"Unknown entity type '{entity_type}' for validation."
                self.add_error(msg)
                ServiceLogger.log_operation_error(logger, operation_desc, Exception(msg))
                return
            if options.must_be_readable and not os.access(path_obj, os.R_OK):
                self.add_error(f"{entity_name} ({entity_type}) is not readable: {path_obj}")
            if options.must_be_writable and not os.access(path_obj, os.W_OK):
                self.add_error(f"{entity_name} ({entity_type}) is not writable: {path_obj}")
            if options.must_be_executable and not os.access(path_obj, os.X_OK):
                self.add_error(f"{entity_name} ({entity_type}) is not executable: {path_obj}")
        if not self.has_errors():
            ServiceLogger.log_operation_success(logger, operation_desc, path=str(path_obj))

    def _ensure_directory_exists_logic(
        self,
        path_obj: Path,
        directory_name: str,
        create_if_missing: bool,
        must_be_writable_after_creation: bool,
    ) -> None:
        """
        Ensures a directory exists, optionally creates it.

        Adds errors on failure.
        """
        operation_desc = f"ensure directory exists '{directory_name}' at {path_obj}"
        ServiceLogger.log_operation_start(logger, operation_desc)
        if not self._ensure_path_exists(path_obj):
            if create_if_missing:
                logger.debug("Creating directory: %s at %s", directory_name, path_obj)
                try:
                    path_obj.mkdir(parents=True, exist_ok=True)
                    if must_be_writable_after_creation and not os.access(path_obj, os.W_OK):
                        self.add_error(
                            f"Created directory {directory_name} but it is not writable: {path_obj}"
                        )
                except (OSError, ValueError) as e:
                    msg = f"Failed to create {directory_name} directory at {path_obj}: {e}"
                    self.add_error(msg)
                    ServiceLogger.log_operation_error(logger, operation_desc, Exception(msg))
                    return
            else:
                self.add_error(
                    f"{directory_name} directory does not exist and creation "
                    f"not enabled: {path_obj}"
                )
        elif not self._is_directory(path_obj):
            self.add_error(f"{directory_name} path exists but is not a directory: {path_obj}")
        elif must_be_writable_after_creation and not os.access(path_obj, os.W_OK):
            self.add_error(f"{directory_name} directory exists but is not writable: {path_obj}")
        if not self.has_errors():
            ServiceLogger.log_operation_success(logger, operation_desc, path=str(path_obj))

    def _validate_user_code_path_logic(self, user_code_path_str: Optional[str]) -> None:
        """
        Validates the user code path if provided. Adds errors on failure.
        """
        operation_desc = f"validate user code path '{user_code_path_str}'"
        ServiceLogger.log_operation_start(logger, operation_desc)
        if not user_code_path_str:
            ServiceLogger.log_operation_success(
                logger, operation_desc, result="Not provided, valid."
            )
            return
        path_obj = Path(user_code_path_str)
        if not self._ensure_path_exists(path_obj):
            self.add_error(f"User code directory does not exist: {path_obj}")
        elif not self._is_directory(path_obj):
            self.add_error(f"User code path is not a directory: {path_obj}")
        elif not os.access(path_obj, os.R_OK):
            self.add_error(f"User code directory is not readable: {path_obj}")
        if not self.has_errors():
            ServiceLogger.log_operation_success(logger, operation_desc, path=str(path_obj))

    def _parse_path_input(self, path_input: Any, operation: str) -> Optional[Path]:
        """Parse path input to Path object."""
        if isinstance(path_input, str) and operation != "validate_user_code_path":
            return Path(path_input)
        if isinstance(path_input, Path):
            return path_input
        return None

    def _handle_user_code_path_operation(self, path_input: Any) -> None:
        """Handle validate_user_code_path operation."""
        if path_input is not None and not isinstance(path_input, str):
            self.add_error("'path' for 'validate_user_code_path' must be a string or None.")
        else:
            self._validate_user_code_path_logic(path_input)

    def _handle_file_or_directory_operation(
        self, operation: str, path_obj: Path, data: Dict[str, Any]
    ) -> None:
        """Handle validate_file or validate_directory operations."""
        path_name = data.get("path_name", str(path_obj))
        if not isinstance(path_name, str):
            path_name = str(path_obj)
        entity_type = "file" if operation == "validate_file" else "directory"
        options = PathValidationOptions(
            required=data.get("required", True),
            must_be_readable=data.get("must_be_readable", True),
            must_be_writable=data.get("must_be_writable", False),
            must_be_executable=data.get("must_be_executable", False),
        )
        self._validate_path_entity_logic(
            path_obj, entity_type=entity_type, entity_name=path_name, options=options
        )

    def _handle_ensure_directory_operation(self, path_obj: Path, data: Dict[str, Any]) -> None:
        """Handle ensure_directory_exists operation."""
        path_name = data.get("path_name", str(path_obj))
        if not isinstance(path_name, str):
            path_name = str(path_obj)
        self._ensure_directory_exists_logic(
            path_obj,
            directory_name=path_name,
            create_if_missing=data.get("create_if_missing", True),
            must_be_writable_after_creation=data.get("must_be_writable_after_creation", True),
        )

    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Validates file or directory paths based on the specified operation.

        Args:
            data: A dictionary containing:
                - "operation" (str): One of "validate_file",
                  "validate_directory", "ensure_directory_exists",
                  "validate_user_code_path".
                - "path" (Union[Path, str]): The path to validate/process.
                - "path_name" (str, optional): Descriptive name for messages.
                  Defaults to path.
                - "required" (bool, optional): Defaults to True.
                  (for validate_file/directory)
                - "must_be_readable" (bool, optional): Defaults to True.
                  (for validate_file/directory)
                - "must_be_writable" (bool, optional): Defaults to False.
                  (for validate_file/directory)
                - "must_be_executable" (bool, optional): Defaults to False.
                  (for validate_file/directory)
                - "create_if_missing" (bool, optional): Defaults to True.
                  (for ensure_directory_exists)
                - "must_be_writable_after_creation" (bool, optional):
                  Defaults to True. (for ensure_directory_exists)

            config: Not actively used by this validator.

        Returns:
            bool: True if validation passes for the operation, False otherwise.
        """
        if not self._prepare_validation(data):
            return False
        operation = data.get("operation")
        path_input = data.get("path")
        if not operation:
            self.add_error("Operation not specified in validation data.")
            return False
        path_obj = self._parse_path_input(path_input, operation)
        if operation == "validate_user_code_path":
            self._handle_user_code_path_operation(path_input)
        elif path_obj is None:
            self.add_error("'path' (Path or str) is required for this operation and must be valid.")
        elif operation in ("validate_file", "validate_directory"):
            self._handle_file_or_directory_operation(operation, path_obj, data)
        elif operation == "ensure_directory_exists":
            self._handle_ensure_directory_operation(path_obj, data)
        else:
            self.add_error(f"Unknown operation: {operation}")
        if self.has_errors():
            combined_msg = "; ".join(self.get_errors())
            ServiceLogger.log_operation_error(
                logger,
                f"PathValidator operation '{operation}' failed",
                Exception(combined_msg),
                error_details=self.get_errors(),
            )
        return not self.has_errors()
