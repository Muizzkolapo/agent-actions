"""
Directory validation utilities.

This module provides utilities for validating directory structures
and ensuring they meet the required constraints.
"""
import os
import logging
from pathlib import Path
from typing import List, Dict, Set, Any, Optional
from agent_actions.validation.base_validator import BaseValidator
logger = logging.getLogger(__name__)

class DirectoryValidator(BaseValidator):
    """
    Handles directory validation operations by inheriting from BaseValidator.
    """

    def _check_required_directories_logic(self, required_dirs: List[Path]) -> None:
        """
        Checks if required directories exist and are accessible. Adds errors if not.
        """
        logger.debug('Checking required directories: %s', [str(d) for d in required_dirs])
        missing_dirs = []
        permission_dirs = []
        not_dirs = []
        for directory in required_dirs:
            if not self._ensure_path_exists(directory):
                missing_dirs.append(directory)
                logger.error('Required directory not found: %s', directory)
                continue
            if not self._is_directory(directory):
                not_dirs.append(directory)
                logger.error('Path exists but is not a directory: %s', directory)
                continue
            if not os.access(directory, os.R_OK):
                permission_dirs.append(directory)
                logger.error('Directory exists but is not readable: %s', directory)
                continue
            logger.debug('Successfully validated directory: %s', directory)
        if missing_dirs:
            self.add_error(f'Missing required directories: {[str(d) for d in missing_dirs]}. Please create them.')
        if not_dirs:
            self.add_error(f'Paths exist but are not directories: {[str(d) for d in not_dirs]}. Please ensure they are directories.')
        if permission_dirs:
            self.add_error(f'Directories exist but are not readable: {[str(d) for d in permission_dirs]}. Please check permissions.')

    def _check_directory_structure_logic(self, base_dir: Path, required_structure: Dict[str, Set[str]]) -> None:
        """
        Checks if a directory has the required structure. Adds errors if not.
        """
        logger.debug('Checking directory structure for: %s', base_dir)
        if not self._ensure_path_exists(base_dir):
            self.add_error(f'Base directory for structure check does not exist: {base_dir}')
            return
        if not self._is_directory(base_dir):
            self.add_error(f'Base path for structure check is not a directory: {base_dir}')
            return
        for subdir_name, required_files in required_structure.items():
            subdir = base_dir / subdir_name
            if not self._ensure_path_exists(subdir):
                self.add_error(f"Required subdirectory '{subdir_name}' does not exist in {base_dir}")
                continue
            if not self._is_directory(subdir):
                self.add_error(f"Path '{subdir_name}' in {base_dir} exists but is not a directory.")
                continue
            for req_file_name in required_files:
                file_path = subdir / req_file_name
                if not self._ensure_path_exists(file_path):
                    self.add_error(f"Required file '{req_file_name}' missing from '{subdir_name}' in {base_dir}.")
                elif not self._is_file(file_path):
                    self.add_error(f"Path '{req_file_name}' in '{subdir_name}' ({base_dir}) exists but is not a file.")
        logger.debug('Directory structure check complete for: %s', base_dir)

    def _ensure_directories_exist_logic(self, directories: List[Path], create_if_missing: bool=True) -> None:
        """
        Ensures directories exist, optionally creating them. Adds errors on failure.
        Returns a list of created directory paths (though this return is not part of BaseValidator's contract).
        """
        logger.debug('Ensuring directories exist: %s (create_if_missing=%s)', [str(d) for d in directories], create_if_missing)
        created_dirs_log: List[Path] = []
        for directory in directories:
            if not self._ensure_path_exists(directory):
                if create_if_missing:
                    try:
                        logger.debug('Creating directory: %s', directory)
                        directory.mkdir(parents=True, exist_ok=True)
                        created_dirs_log.append(directory)
                    except Exception as e:
                        self.add_error(f'Could not create directory {directory}: {e}')
                else:
                    self.add_error(f'Directory does not exist and creation is not enabled: {directory}')
            elif not self._is_directory(directory):
                self.add_error(f'Path exists but is not a directory: {directory}')
        if created_dirs_log:
            logger.debug('Successfully created directories: %s', [str(d) for d in created_dirs_log])

    def _check_write_permissions_logic(self, directories: List[Path]) -> None:
        """
        Checks if directories are writable. Adds errors if not.
        """
        logger.debug('Checking write permissions for: %s', [str(d) for d in directories])
        not_writable = []
        for directory in directories:
            if not self._ensure_path_exists(directory):
                self.add_error(f'Cannot check write permissions; directory does not exist: {directory}')
                continue
            if not self._is_directory(directory):
                self.add_error(f'Cannot check write permissions; path is not a directory: {directory}')
                continue
            if not os.access(directory, os.W_OK):
                not_writable.append(directory)
        if not_writable:
            self.add_error(f'Directories are not writable: {[str(d) for d in not_writable]}. Please check permissions.')

    def validate(self, data: Any, config: Optional[Dict[str, Any]]=None) -> bool:
        """
        Validates directory-related operations.

        Args:
            data: A dictionary containing:
                - "operation" (str): One of "check_required", "check_structure",
                                     "ensure_exists", "check_write_permissions".
                - And other keys based on the operation:
                    - for "check_required": "paths_to_check" (List[Path])
                    - for "check_structure": "base_dir" (Path),
                                             "required_structure" (Dict[str, Set[str]])
                    - for "ensure_exists": "paths_to_check" (List[Path]),
                                           "create_if_missing" (bool, optional, default True)
                    - for "check_write_permissions": "paths_to_check" (List[Path])
            config: Not actively used by this validator but part of the interface.

        Returns:
            bool: True if validation passes for the operation, False otherwise.
        """
        self.clear_errors()
        self.clear_warnings()
        if not isinstance(data, dict):
            self.add_error('Validation data must be a dictionary.')
            return False
        operation = data.get('operation')
        if not operation:
            self.add_error('Operation not specified in validation data.')
            return False
        logger.debug('DirectoryValidator performing operation: %s with data: %s', operation, data)
        if operation == 'check_required':
            paths_to_check = data.get('paths_to_check')
            if not isinstance(paths_to_check, list) or not all((isinstance(p, Path) for p in paths_to_check)):
                self.add_error("'paths_to_check' (List[Path]) is required for 'check_required' operation.")
            else:
                self._check_required_directories_logic(paths_to_check)
        elif operation == 'check_structure':
            base_dir = data.get('base_dir')
            required_structure = data.get('required_structure')
            if not isinstance(base_dir, Path) or not isinstance(required_structure, dict):
                self.add_error("'base_dir' (Path) and 'required_structure' (Dict) are required for 'check_structure'.")
            else:
                self._check_directory_structure_logic(base_dir, required_structure)
        elif operation == 'ensure_exists':
            paths_to_check = data.get('paths_to_check')
            create_if_missing = data.get('create_if_missing', True)
            if not isinstance(paths_to_check, list) or not all((isinstance(p, Path) for p in paths_to_check)) or (not isinstance(create_if_missing, bool)):
                self.add_error("'paths_to_check' (List[Path]) and 'create_if_missing' (bool) are required for 'ensure_exists'.")
            else:
                self._ensure_directories_exist_logic(paths_to_check, create_if_missing)
        elif operation == 'check_write_permissions':
            paths_to_check = data.get('paths_to_check')
            if not isinstance(paths_to_check, list) or not all((isinstance(p, Path) for p in paths_to_check)):
                self.add_error("'paths_to_check' (List[Path]) is required for 'check_write_permissions'.")
            else:
                self._check_write_permissions_logic(paths_to_check)
        else:
            self.add_error(f'Unknown operation: {operation}')
        return not self.has_errors()