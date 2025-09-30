"""
Path validation utilities.

This module provides common utilities for validating file and directory paths,
now conforming to the BaseValidator interface.
"""

import os
import logging
from pathlib import Path
from typing import Optional, Any, Dict

# Assuming BaseValidator is in validators.base_validator
from agent_actions.agents.base.base_validator import BaseValidator
# Assuming ServiceLogger and custom exceptions exist.
# Exceptions are no longer directly raised by validation logic.
from agent_actions.cli.utils.service_logger import ServiceLogger
# from agent_actions.core.exceptions import (
#     DirectoryNotFoundError,
#     FileNotFoundError,
#     ValidationError,
#     PermissionError
# )

logger = logging.getLogger(__name__)


class PathValidator(BaseValidator):
    """
    Utility class for validating file and directory paths,
    inheriting from BaseValidator.
    """

    def _validate_path_entity_logic(
        self,
        path_obj: Path,
        entity_type: str, # "file" or "directory"
        entity_name: str,
        required: bool,
        must_be_readable: bool,
        must_be_writable: bool,
        must_be_executable: bool
    ) -> None:
        """
        Generic logic to validate a path (file or directory) and add errors.
        """
        operation_desc = f"validate {entity_type} '{entity_name}' at {path_obj}"
        ServiceLogger.log_operation_start(logger, operation_desc)

        path_exists = self._ensure_path_exists(path_obj)

        if required and not path_exists:
            msg = f"{entity_name} ({entity_type}) does not exist: {path_obj}"
            self.add_error(msg)
            ServiceLogger.log_operation_error(logger, operation_desc, Exception(msg))
            return  # Cannot perform further checks

        if path_exists: # Only check type and permissions if it exists
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
            else: # Should not happen if called correctly
                msg = f"Unknown entity type '{entity_type}' for path validation."
                self.add_error(msg)
                ServiceLogger.log_operation_error(logger, operation_desc, Exception(msg))
                return


            if must_be_readable and not os.access(path_obj, os.R_OK):
                self.add_error(f"{entity_name} ({entity_type}) is not readable: {path_obj}")
            if must_be_writable and not os.access(path_obj, os.W_OK):
                self.add_error(f"{entity_name} ({entity_type}) is not writable: {path_obj}")
            if must_be_executable and not os.access(path_obj, os.X_OK):
                self.add_error(f"{entity_name} ({entity_type}) is not executable: {path_obj}")
        
        # If errors were added by os.access checks, ServiceLogger will catch them via has_errors in validate
        # For now, we just log success if we reach here without early exit with error
        if not self.has_errors(): # Check errors specific to this sub-operation if possible
             ServiceLogger.log_operation_success(logger, operation_desc, path=str(path_obj))


    def _ensure_directory_exists_logic(
        self,
        path_obj: Path,
        directory_name: str,
        create_if_missing: bool,
        must_be_writable_after_creation: bool
    ) -> None:
        """
        Ensures a directory exists, optionally creates it. Adds errors on failure.
        """
        operation_desc = f"ensure directory exists '{directory_name}' at {path_obj}"
        ServiceLogger.log_operation_start(logger, operation_desc)

        if not self._ensure_path_exists(path_obj):
            if create_if_missing:
                logger.debug(f"Creating directory: {directory_name} at {path_obj}")
                try:
                    path_obj.mkdir(parents=True, exist_ok=True)
                    # Check writability after creation if required
                    if must_be_writable_after_creation and not os.access(path_obj, os.W_OK):
                        self.add_error(f"Created directory {directory_name} but it is not writable: {path_obj}")
                except Exception as e:
                    msg = f"Failed to create {directory_name} directory at {path_obj}: {e}"
                    self.add_error(msg)
                    ServiceLogger.log_operation_error(logger, operation_desc, Exception(msg))
                    return
            else:
                self.add_error(f"{directory_name} directory does not exist and creation not enabled: {path_obj}")
        elif not self._is_directory(path_obj):
             self.add_error(f"{directory_name} path exists but is not a directory: {path_obj}")
        elif must_be_writable_after_creation and not os.access(path_obj, os.W_OK): # Exists, check writability
            self.add_error(f"{directory_name} directory exists but is not writable: {path_obj}")
        
        if not self.has_errors(): # Check errors specific to this sub-operation
            ServiceLogger.log_operation_success(logger, operation_desc, path=str(path_obj))


    def _validate_user_code_path_logic(self, user_code_path_str: Optional[str]) -> None:
        """
        Validates the user code path if provided. Adds errors on failure.
        """
        operation_desc = f"validate user code path '{user_code_path_str}'"
        ServiceLogger.log_operation_start(logger, operation_desc)

        if not user_code_path_str: # If None or empty, it's valid (means not provided)
            ServiceLogger.log_operation_success(logger, operation_desc, result="Not provided, valid.")
            return

        path_obj = Path(user_code_path_str)

        if not self._ensure_path_exists(path_obj):
            self.add_error(f"User code directory does not exist: {path_obj}")
        elif not self._is_directory(path_obj):
            self.add_error(f"User code path is not a directory: {path_obj}")
        elif not os.access(path_obj, os.R_OK): # Must be readable
            self.add_error(f"User code directory is not readable: {path_obj}")
        
        if not self.has_errors(): # Check errors specific to this sub-operation
             ServiceLogger.log_operation_success(logger, operation_desc, path=str(path_obj))


    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Validates file or directory paths based on the specified operation.

        Args:
            data: A dictionary containing:
                - "operation" (str): One of "validate_file", "validate_directory",
                                     "ensure_directory_exists", "validate_user_code_path".
                - "path" (Union[Path, str]): The path to validate/process.
                - "path_name" (str, optional): Descriptive name for messages. Defaults to path.
                - "required" (bool, optional): Defaults to True. (for validate_file/directory)
                - "must_be_readable" (bool, optional): Defaults to True. (for validate_file/directory)
                - "must_be_writable" (bool, optional): Defaults to False. (for validate_file/directory)
                - "must_be_executable" (bool, optional): Defaults to False. (for validate_file/directory)
                - "create_if_missing" (bool, optional): Defaults to True. (for ensure_directory_exists)
                - "must_be_writable_after_creation" (bool, optional): Defaults to True. (for ensure_directory_exists)

            config: Not actively used by this validator.

        Returns:
            bool: True if validation passes for the operation, False otherwise.
        """
        self.clear_errors()
        self.clear_warnings()

        if not isinstance(data, dict):
            self.add_error("Validation data must be a dictionary.")
            return False

        operation = data.get("operation")
        path_input = data.get("path")

        if not operation:
            self.add_error("Operation not specified in validation data.")
            return False
        
        # Convert string path to Path object early for most operations
        path_obj: Optional[Path] = None
        if isinstance(path_input, str) and operation != "validate_user_code_path":
            path_obj = Path(path_input)
        elif isinstance(path_input, Path):
            path_obj = path_input
        
        # User code path is handled specially as it can be None or str
        if operation == "validate_user_code_path":
            if path_input is not None and not isinstance(path_input, str):
                 self.add_error("'path' for 'validate_user_code_path' must be a string or None.")
            else:
                self._validate_user_code_path_logic(path_input) # type: ignore
        elif path_obj is None: # path_obj is required for other operations
            self.add_error("'path' (Path or str) is required for this operation and must be valid.")
        else:
            path_name = data.get("path_name", str(path_obj))
            if not isinstance(path_name, str): path_name = str(path_obj) # Ensure path_name is str

            if operation == "validate_file" or operation == "validate_directory":
                entity_type = "file" if operation == "validate_file" else "directory"
                self._validate_path_entity_logic(
                    path_obj,
                    entity_type=entity_type,
                    entity_name=path_name,
                    required=data.get("required", True),
                    must_be_readable=data.get("must_be_readable", True),
                    must_be_writable=data.get("must_be_writable", False),
                    must_be_executable=data.get("must_be_executable", False)
                )
            elif operation == "ensure_directory_exists":
                self._ensure_directory_exists_logic(
                    path_obj,
                    directory_name=path_name,
                    create_if_missing=data.get("create_if_missing", True),
                    must_be_writable_after_creation=data.get("must_be_writable_after_creation", True)
                )
            else:
                self.add_error(f"Unknown operation: {operation}")
        
        # Log overall operation failure if errors were added by sub-logics
        # ServiceLogger is called within sub-logics, this is a fallback.
        if self.has_errors():
            combined_msg = "; ".join(self.get_errors())
            ServiceLogger.log_operation_error(
                logger,
                f"PathValidator operation '{operation}' failed",
                Exception(combined_msg),
                error_details=self.get_errors()
            )
        
        return not self.has_errors()
