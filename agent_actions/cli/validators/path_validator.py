"""
Path validation utilities.

This module provides common utilities for validating file and directory paths.
"""

import os
import logging
from pathlib import Path
from typing import Optional, Union

from agent_actions.cli.exceptions import (
    DirectoryNotFoundError,
    FileNotFoundError,
    ValidationError,
    PermissionError
)
from agent_actions.cli.utils.service_logger import ServiceLogger

logger = logging.getLogger(__name__)


class PathValidator:
    """Utility class for validating file and directory paths."""
    
    @staticmethod
    def validate_directory(
        path: Path,
        directory_name: str,
        required: bool = True,
        must_be_readable: bool = True,
        must_be_writable: bool = False,
        must_be_executable: bool = False
    ) -> Path:
        """
        Validate that a directory exists and is accessible.
        
        Args:
            path: Path to the directory.
            directory_name: Name of the directory (for error messages).
            required: Whether the directory is required to exist.
            must_be_readable: Whether the directory must be readable.
            must_be_writable: Whether the directory must be writable.
            must_be_executable: Whether the directory must be executable.
            
        Returns:
            Path object if valid.
            
        Raises:
            DirectoryNotFoundError: If the directory does not exist and is required.
            ValidationError: If the path is not a directory.
            PermissionError: If the directory is not accessible.
        """
        try:
            ServiceLogger.log_operation_start(logger, "validate directory", 
                                           path=str(path),
                                           name=directory_name)
            
            path_obj = Path(path)
            
            if required and not path_obj.exists():
                error_msg = f"{directory_name} directory does not exist: {path_obj}"
                logger.error(error_msg)
                raise DirectoryNotFoundError(error_msg)
                
            if not path_obj.is_dir():
                error_msg = f"{directory_name} path is not a directory: {path_obj}"
                logger.error(error_msg)
                raise ValidationError(error_msg)
                
            if must_be_readable and not os.access(path_obj, os.R_OK):
                error_msg = f"{directory_name} directory is not readable: {path_obj}"
                logger.error(error_msg)
                raise PermissionError(error_msg)
                
            if must_be_writable and not os.access(path_obj, os.W_OK):
                error_msg = f"{directory_name} directory is not writable: {path_obj}"
                logger.error(error_msg)
                raise PermissionError(error_msg)
                
            if must_be_executable and not os.access(path_obj, os.X_OK):
                error_msg = f"{directory_name} directory is not executable: {path_obj}"
                logger.error(error_msg)
                raise PermissionError(error_msg)
            
            ServiceLogger.log_operation_success(logger, "validate directory", 
                                             path=str(path_obj))
            return path_obj
            
        except Exception as e:
            ServiceLogger.log_operation_error(logger, "validate directory", e)
            raise
    
    @staticmethod
    def validate_file(
        path: Path,
        file_name: str,
        required: bool = True,
        must_be_readable: bool = True,
        must_be_writable: bool = False,
        must_be_executable: bool = False
    ) -> Path:
        """
        Validate that a file exists and is accessible.
        
        Args:
            path: Path to the file.
            file_name: Name of the file (for error messages).
            required: Whether the file is required to exist.
            must_be_readable: Whether the file must be readable.
            must_be_writable: Whether the file must be writable.
            must_be_executable: Whether the file must be executable.
            
        Returns:
            Path object if valid.
            
        Raises:
            FileNotFoundError: If the file does not exist and is required.
            ValidationError: If the path is not a file.
            PermissionError: If the file is not accessible.
        """
        try:
            ServiceLogger.log_operation_start(logger, "validate file", 
                                           path=str(path),
                                           name=file_name)
            
            path_obj = Path(path)
            
            if required and not path_obj.exists():
                error_msg = f"{file_name} file does not exist: {path_obj}"
                logger.error(error_msg)
                raise FileNotFoundError(error_msg)
                
            if not path_obj.is_file():
                error_msg = f"{file_name} path is not a file: {path_obj}"
                logger.error(error_msg)
                raise ValidationError(error_msg)
                
            if must_be_readable and not os.access(path_obj, os.R_OK):
                error_msg = f"{file_name} file is not readable: {path_obj}"
                logger.error(error_msg)
                raise PermissionError(error_msg)
                
            if must_be_writable and not os.access(path_obj, os.W_OK):
                error_msg = f"{file_name} file is not writable: {path_obj}"
                logger.error(error_msg)
                raise PermissionError(error_msg)
                
            if must_be_executable and not os.access(path_obj, os.X_OK):
                error_msg = f"{file_name} file is not executable: {path_obj}"
                logger.error(error_msg)
                raise PermissionError(error_msg)
            
            ServiceLogger.log_operation_success(logger, "validate file", 
                                             path=str(path_obj))
            return path_obj
            
        except Exception as e:
            ServiceLogger.log_operation_error(logger, "validate file", e)
            raise
    
    @staticmethod
    def create_directory_if_needed(
        path: Path,
        directory_name: str,
        must_be_writable: bool = True
    ) -> Path:
        """
        Create a directory if it doesn't exist.
        
        Args:
            path: Path to the directory.
            directory_name: Name of the directory (for error messages).
            must_be_writable: Whether the directory must be writable.
            
        Returns:
            Path object of the created/existing directory.
            
        Raises:
            PermissionError: If the directory cannot be created.
        """
        try:
            ServiceLogger.log_operation_start(logger, "create directory", 
                                           path=str(path),
                                           name=directory_name)
            
            path_obj = Path(path)
            
            if not path_obj.exists():
                logger.debug(f"Creating directory: {directory_name} at {path_obj}")
                try:
                    path_obj.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    error_msg = f"Failed to create {directory_name} directory: {path_obj}: {str(e)}"
                    logger.error(error_msg)
                    raise PermissionError(error_msg) from e
            
            if must_be_writable and not os.access(path_obj, os.W_OK):
                error_msg = f"{directory_name} is not writable: {path_obj}"
                logger.error(error_msg)
                raise PermissionError(error_msg)
            
            ServiceLogger.log_operation_success(logger, "create directory", 
                                             path=str(path_obj))
            return path_obj
            
        except Exception as e:
            ServiceLogger.log_operation_error(logger, "create directory", e)
            raise
    
    @staticmethod
    def validate_user_code_path(user_code: Optional[str]) -> Optional[str]:
        """
        Validate the user code path if provided.
        
        Args:
            user_code: Path to user-defined functions directory.
            
        Returns:
            Validated user code path if provided and valid, None otherwise.
            
        Raises:
            ValidationError: If the user code path is invalid.
        """
        try:
            ServiceLogger.log_operation_start(logger, "validate user code path", 
                                           user_code=user_code)
            
            if not user_code:
                return None
                
            path_obj = Path(user_code)
            
            if not path_obj.exists():
                raise ValidationError(f"User code directory does not exist: {path_obj}")
                
            if not path_obj.is_dir():
                raise ValidationError(f"User code path is not a directory: {path_obj}")
                
            if not os.access(path_obj, os.R_OK):
                raise ValidationError(f"User code directory is not readable: {path_obj}")
                
            ServiceLogger.log_operation_success(logger, "validate user code path", 
                                             path=str(path_obj))
            return str(path_obj)
            
        except Exception as e:
            ServiceLogger.log_operation_error(logger, "validate user code path", e)
            raise