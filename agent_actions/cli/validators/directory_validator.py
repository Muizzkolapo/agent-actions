"""
Directory validation utilities.

This module provides utilities for validating directory structures
and ensuring they meet the required constraints.
"""

import os
import logging
from pathlib import Path
from typing import List, Dict, Set, Optional

from agent_actions.cli.exceptions import (
    DirectoryNotFoundError,
    PermissionError,
    ValidationError
)

logger = logging.getLogger(__name__)


class DirectoryValidator:
    """Handles directory validation operations."""
    
    @staticmethod
    def check_required_directories(required_dirs: List[Path]) -> None:
        """
        Check if required directories exist and are accessible.

        Args:
            required_dirs: List of directory paths to check.
            
        Raises:
            DirectoryNotFoundError: If any required directory does not exist.
            PermissionError: If any required directory is not accessible.
        """
        logger.info("Starting directory validation", extra={
            'required_dirs': [str(d) for d in required_dirs]
        })
        
        missing_dirs = []
        permission_dirs = []
        not_dirs = []
        
        for directory in required_dirs:
            try:
                if not directory.exists():
                    missing_dirs.append(directory)
                    logger.error("Required directory not found", extra={
                        'directory': str(directory)
                    })
                    continue
                
                if not directory.is_dir():
                    not_dirs.append(directory)
                    logger.error("Path exists but is not a directory", extra={
                        'directory': str(directory)
                    })
                    continue
                
                if not os.access(directory, os.R_OK):
                    permission_dirs.append(directory)
                    logger.error("Directory exists but is not readable", extra={
                        'directory': str(directory)
                    })
                    continue
                
                logger.debug(f"Successfully validated directory: {directory}")
                
            except Exception as e:
                logger.error(f"Error validating directory {directory}: {str(e)}", exc_info=True)
                missing_dirs.append(directory)
        
        # Report errors with detailed information
        if missing_dirs or permission_dirs or not_dirs:
            error_messages = []
            
            if missing_dirs:
                error_messages.append("The following required directories are missing:")
                for dir_path in missing_dirs:
                    error_messages.append(f"  - {dir_path}")
                error_messages.append(f"\nPlease create these directories before proceeding.")
            
            if not_dirs:
                error_messages.append("The following paths exist but are not directories:")
                for dir_path in not_dirs:
                    error_messages.append(f"  - {dir_path}")
                error_messages.append(f"\nPlease ensure these paths point to directories.")
            
            if permission_dirs:
                error_messages.append("The following directories exist but are not readable:")
                for dir_path in permission_dirs:
                    error_messages.append(f"  - {dir_path}")
                error_messages.append(f"\nPlease check the permissions on these directories.")
            
            error_msg = "\n".join(error_messages)
            logger.error("Directory validation failed", extra={
                'missing_directories': [str(d) for d in missing_dirs],
                'permission_directories': [str(d) for d in permission_dirs],
                'not_directories': [str(d) for d in not_dirs],
                'error_message': error_msg
            })
            
            # Raise the most appropriate exception
            if missing_dirs:
                raise DirectoryNotFoundError(error_msg)
            elif permission_dirs:
                raise PermissionError(error_msg)
            else:
                raise ValidationError(error_msg)
        
        logger.info("Directory validation successful", extra={
            'validated_directories': [str(d) for d in required_dirs]
        })
    
    @staticmethod
    def check_directory_structure(base_dir: Path, required_structure: Dict[str, Set[str]]) -> None:
        """
        Check if a directory has the required structure.
        
        Args:
            base_dir: Base directory to check.
            required_structure: Dictionary mapping subdirectory names to sets of required file names.
            
        Raises:
            DirectoryNotFoundError: If the base directory or any required subdirectory does not exist.
            ValidationError: If the structure does not match requirements.
        """
        logger.info(f"Checking directory structure for: {base_dir}")
        
        # Check if base directory exists
        if not base_dir.exists():
            raise DirectoryNotFoundError(f"Base directory does not exist: {base_dir}")
        
        if not base_dir.is_dir():
            raise ValidationError(f"Base path is not a directory: {base_dir}")
        
        # Check structure
        errors = []
        for subdir_name, required_files in required_structure.items():
            subdir = base_dir / subdir_name
            
            # Check if subdirectory exists
            if not subdir.exists():
                errors.append(f"Required subdirectory '{subdir_name}' does not exist")
                continue
            
            if not subdir.is_dir():
                errors.append(f"'{subdir_name}' exists but is not a directory")
                continue
            
            # Check required files
            for req_file in required_files:
                file_path = subdir / req_file
                if not file_path.exists():
                    errors.append(f"Required file '{req_file}' missing from '{subdir_name}' directory")
                elif not file_path.is_file():
                    errors.append(f"'{req_file}' in '{subdir_name}' exists but is not a file")
        
        if errors:
            error_msg = "Directory structure validation failed:\n" + "\n".join(errors)
            logger.error(error_msg)
            raise ValidationError(error_msg)
        
        logger.info(f"Directory structure validation successful for: {base_dir}")
    
    @staticmethod
    def ensure_directories_exist(directories: List[Path], create_if_missing: bool = True) -> List[Path]:
        """
        Ensure that directories exist, optionally creating them if missing.
        
        Args:
            directories: List of directories to check.
            create_if_missing: Whether to create missing directories.
            
        Returns:
            List of directories that were created.
            
        Raises:
            PermissionError: If directories could not be created.
        """
        created_dirs = []
        
        for directory in directories:
            if not directory.exists():
                if create_if_missing:
                    try:
                        logger.debug(f"Creating directory: {directory}")
                        directory.mkdir(parents=True, exist_ok=True)
                        created_dirs.append(directory)
                    except Exception as e:
                        raise PermissionError(f"Could not create directory {directory}: {str(e)}") from e
                else:
                    logger.warning(f"Directory does not exist and won't be created: {directory}")
        
        return created_dirs
    
    @staticmethod
    def check_write_permissions(directories: List[Path]) -> None:
        """
        Check if directories are writable.
        
        Args:
            directories: List of directories to check.
            
        Raises:
            PermissionError: If any directory is not writable.
        """
        not_writable = []
        
        for directory in directories:
            if not directory.exists():
                not_writable.append(directory)
                continue
                
            if not os.access(directory, os.W_OK):
                not_writable.append(directory)
        
        if not_writable:
            dirs_str = "\n  - ".join([str(d) for d in not_writable])
            error_msg = f"The following directories are not writable:\n  - {dirs_str}"
            logger.error(error_msg)
            raise PermissionError(error_msg)