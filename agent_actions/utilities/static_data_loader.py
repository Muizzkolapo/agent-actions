"""
Static Data Loader for Context Scope Static Data Loading.

This module provides functionality to load external reference files (JSON, YAML,
Markdown, CSV) in workflow configurations through context_scope.static_data.

Features:
- Parses $file: prefix syntax
- Loads files from static_data/ or seed/ folder only
- Supports JSON, YAML, Markdown, CSV, and plain text
- Caches loaded data per workflow run
- Prevents path traversal outside static data folder
"""

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from agent_actions.errors import FileSystemError  # New modular pattern!

logger = logging.getLogger(__name__)


class StaticDataLoadError(FileSystemError):
    """Exception raised during static data loading."""

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ):
        """Initialize StaticDataLoadError.

        Args:
            message: The error message
            context: Additional context dict with error details
            cause: The underlying exception that caused this error
        """
        ctx = context or {}
        ctx['operation'] = 'load_static_data'
        super().__init__(message, context=ctx, cause=cause)


class StaticDataLoader:
    """
    Loads static/seed data files from designated static_data/ or seed/ folder.

    Features:
    - Parses $file: prefix syntax
    - Loads files from static_data/ or seed/ folder only
    - Supports JSON, YAML, Markdown, CSV, and plain text
    - Caches loaded data per workflow run
    - Prevents path traversal outside static data folder
    """

    # File size limit: 10MB to prevent memory issues
    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

    # Supported file extensions
    SUPPORTED_EXTENSIONS = {'.json', '.yml', '.yaml', '.md', '.txt', '.csv'}

    def __init__(self, static_data_dir: Path):
        """
        Initialize StaticDataLoader.

        Args:
            static_data_dir: Path to the static_data/ or seed/ folder
                            containing static data files

        Raises:
            ValueError: If static_data_dir doesn't exist or is not a directory
        """
        if not static_data_dir.exists():
            raise ValueError(f"Static data directory does not exist: {static_data_dir}")
        if not static_data_dir.is_dir():
            raise ValueError(f"Static data path is not a directory: {static_data_dir}")

        self.static_data_dir = static_data_dir.resolve()
        self._cache: Dict[str, Any] = {}

        logger.debug(f"StaticDataLoader initialized with directory: {self.static_data_dir}")

    def load_static_data(
        self,
        static_data_config: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Load all static data files specified in context_scope.static_data.

        Args:
            static_data_config: Dictionary mapping field names to file paths
                               (e.g., {'exam_syllabus': '$file:syllabus.json'})

        Returns:
            Dictionary mapping field names to loaded data

        Raises:
            StaticDataLoadError: If file not found, invalid format, or security violation
        """
        if not static_data_config:
            logger.debug("No static data config provided, skipping load")
            return {}

        loaded_data = {}

        for field_name, file_spec in static_data_config.items():
            try:
                # Parse file path from specification
                file_path = self._parse_file_path(file_spec, field_name)

                # Resolve and validate path
                resolved_path = self._resolve_path(file_path, field_name)

                # Check cache
                cache_key = str(resolved_path)
                if cache_key in self._cache:
                    logger.debug(f"Cache hit for field '{field_name}': {cache_key}")
                    loaded_data[field_name] = self._cache[cache_key]
                else:
                    # Load and cache
                    logger.debug(f"Loading file for field '{field_name}': {resolved_path}")
                    data = self._load_file(resolved_path, field_name)
                    self._cache[cache_key] = data
                    loaded_data[field_name] = data
                    logger.debug(f"Loaded static data field '{field_name}' from {resolved_path.name}")

            except StaticDataLoadError:
                # Re-raise StaticDataLoadError as-is
                raise
            except Exception as e:
                # Wrap unexpected errors
                logger.error(f"Unexpected error loading field '{field_name}': {e}")
                raise StaticDataLoadError(
                    f"Failed to load static data field '{field_name}': {str(e)}",
                    context={
                        'field_name': field_name,
                        'file_spec': file_spec,
                        'error_type': 'unexpected_error'
                    },
                    cause=e
                )

        logger.debug(f"Loaded {len(loaded_data)} static data fields: {list(loaded_data.keys())}")
        return loaded_data

    def _parse_file_path(self, file_spec: str, field_name: str) -> str:
        """
        Parse file path from $file: prefix syntax.

        Args:
            file_spec: File specification (e.g., '$file:path.json' or 'path.json')
            field_name: Field name for error messages

        Returns:
            Parsed file path without prefix
        """
        if file_spec.startswith('$file:'):
            return file_spec[6:]  # Remove '$file:' prefix
        else:
            return file_spec  # Use as-is

    def _resolve_path(self, file_path: str, field_name: str) -> Path:
        """
        Resolve file path relative to static_data_dir.

        Args:
            file_path: Relative file path
            field_name: Field name for error messages

        Returns:
            Resolved absolute path

        Raises:
            StaticDataLoadError: If path is absolute or escapes static_data_dir
        """
        path = Path(file_path)

        # Reject absolute paths immediately
        if path.is_absolute():
            logger.error(f"Absolute path rejected for field '{field_name}': {file_path}")
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Absolute paths not allowed",
                context={
                    'field_name': field_name,
                    'file_path': file_path,
                    'error_type': 'absolute_path_not_allowed',
                    'static_data_dir': str(self.static_data_dir)
                }
            )

        # Resolve relative to static_data_dir
        resolved = (self.static_data_dir / path).resolve()

        # Validate security
        self._validate_path_security(resolved, field_name, file_path)

        logger.debug(f"Resolved path for field '{field_name}': {resolved}")
        return resolved

    def _validate_path_security(
        self,
        resolved_path: Path,
        field_name: str,
        original_path: str
    ) -> None:
        """
        Validate that resolved path doesn't escape static_data_dir.

        Args:
            resolved_path: Resolved absolute path
            field_name: Field name for error messages
            original_path: Original path specification for error messages

        Raises:
            StaticDataLoadError: If path escapes static_data_dir
        """
        try:
            # This will raise ValueError if path is outside static_data_dir
            resolved_path.relative_to(self.static_data_dir)
        except ValueError:
            logger.error(
                f"Path traversal attempt detected for field '{field_name}': "
                f"{original_path} -> {resolved_path}"
            )
            raise StaticDataLoadError(
                f"Static data field '{field_name}': File path escapes static data directory",
                context={
                    'field_name': field_name,
                    'original_path': original_path,
                    'resolved_path': str(resolved_path),
                    'static_data_dir': str(self.static_data_dir),
                    'error_type': 'path_traversal_attempt'
                }
            )

    def _load_file(self, file_path: Path, field_name: str) -> Any:
        """
        Load file content based on file extension.

        Args:
            file_path: Absolute resolved file path
            field_name: Field name for error messages

        Returns:
            Loaded and parsed file content

        Raises:
            StaticDataLoadError: If file doesn't exist, is too large, or has unsupported format
        """
        # Check if file exists
        if not file_path.exists():
            raise StaticDataLoadError(
                f"Static data field '{field_name}': File not found",
                context={
                    'field_name': field_name,
                    'file_path': str(file_path),
                    'error_type': 'file_not_found'
                }
            )

        # Check file size
        file_size = file_path.stat().st_size
        if file_size > self.MAX_FILE_SIZE_BYTES:
            raise StaticDataLoadError(
                f"Static data field '{field_name}': File too large "
                f"({file_size / 1024 / 1024:.2f}MB, max {self.MAX_FILE_SIZE_BYTES / 1024 / 1024}MB)",
                context={
                    'field_name': field_name,
                    'file_path': str(file_path),
                    'file_size_bytes': file_size,
                    'max_size_bytes': self.MAX_FILE_SIZE_BYTES,
                    'error_type': 'file_too_large'
                }
            )

        # Dispatch to format-specific loader
        suffix = file_path.suffix.lower()

        if suffix == '.json':
            return self._load_json(file_path, field_name)
        elif suffix in {'.yml', '.yaml'}:
            return self._load_yaml(file_path, field_name)
        elif suffix in {'.md', '.txt'}:
            return self._load_text(file_path, field_name)
        elif suffix == '.csv':
            return self._load_csv(file_path, field_name)
        else:
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Unsupported file type '{suffix}'",
                context={
                    'field_name': field_name,
                    'file_path': str(file_path),
                    'file_type': suffix,
                    'supported_types': list(self.SUPPORTED_EXTENSIONS),
                    'error_type': 'unsupported_format'
                }
            )

    def _load_json(self, file_path: Path, field_name: str) -> Any:
        """
        Load JSON file.

        Args:
            file_path: Path to JSON file
            field_name: Field name for error messages

        Returns:
            Parsed JSON object (dict, list, etc.)

        Raises:
            StaticDataLoadError: If JSON parsing fails
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in field '{field_name}': {e}")
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Invalid JSON format",
                context={
                    'field_name': field_name,
                    'file_path': str(file_path),
                    'parse_error': str(e),
                    'line': e.lineno if hasattr(e, 'lineno') else None,
                    'column': e.colno if hasattr(e, 'colno') else None,
                    'error_type': 'json_parse_error'
                },
                cause=e
            )
        except Exception as e:
            logger.error(f"Error reading JSON file for field '{field_name}': {e}")
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Failed to read JSON file",
                context={
                    'field_name': field_name,
                    'file_path': str(file_path),
                    'error': str(e),
                    'error_type': 'json_read_error'
                },
                cause=e
            )

    def _load_yaml(self, file_path: Path, field_name: str) -> Any:
        """
        Load YAML file.

        Args:
            file_path: Path to YAML file
            field_name: Field name for error messages

        Returns:
            Parsed YAML object (dict, list, etc.)

        Raises:
            StaticDataLoadError: If YAML parsing fails
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.error(f"YAML parse error in field '{field_name}': {e}")
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Invalid YAML format",
                context={
                    'field_name': field_name,
                    'file_path': str(file_path),
                    'parse_error': str(e),
                    'error_type': 'yaml_parse_error'
                },
                cause=e
            )
        except Exception as e:
            logger.error(f"Error reading YAML file for field '{field_name}': {e}")
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Failed to read YAML file",
                context={
                    'field_name': field_name,
                    'file_path': str(file_path),
                    'error': str(e),
                    'error_type': 'yaml_read_error'
                },
                cause=e
            )

    def _load_text(self, file_path: Path, field_name: str) -> str:
        """
        Load plain text or Markdown file.

        Args:
            file_path: Path to text/Markdown file
            field_name: Field name for error messages

        Returns:
            File content as string

        Raises:
            StaticDataLoadError: If file reading fails
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading text file for field '{field_name}': {e}")
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Failed to read text file",
                context={
                    'field_name': field_name,
                    'file_path': str(file_path),
                    'error': str(e),
                    'error_type': 'text_read_error'
                },
                cause=e
            )

    def _load_csv(self, file_path: Path, field_name: str) -> list:
        """
        Load CSV file as list of dictionaries.

        Args:
            file_path: Path to CSV file
            field_name: Field name for error messages

        Returns:
            List of dictionaries (with headers as keys)

        Raises:
            StaticDataLoadError: If CSV parsing fails
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                return list(reader)
        except csv.Error as e:
            logger.error(f"CSV parse error in field '{field_name}': {e}")
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Invalid CSV format",
                context={
                    'field_name': field_name,
                    'file_path': str(file_path),
                    'parse_error': str(e),
                    'error_type': 'csv_parse_error'
                },
                cause=e
            )
        except Exception as e:
            logger.error(f"Error reading CSV file for field '{field_name}': {e}")
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Failed to read CSV file",
                context={
                    'field_name': field_name,
                    'file_path': str(file_path),
                    'error': str(e),
                    'error_type': 'csv_read_error'
                },
                cause=e
            )

    def clear_cache(self) -> None:
        """Clear the file cache (typically called between workflow runs)."""
        num_files = len(self._cache)
        self._cache.clear()
        logger.debug(f"Cache cleared ({num_files} files removed)")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics for debugging.

        Returns:
            Dictionary with cache statistics including:
            - cached_files: Number of files in cache
            - cached_file_paths: List of cached file paths
            - total_size_bytes: Estimated total cache size in bytes
            - total_size_mb: Estimated total cache size in MB
        """
        import sys

        # Estimate cache size
        total_size = sum(
            sys.getsizeof(value)
            for value in self._cache.values()
        )

        return {
            'cached_files': len(self._cache),
            'cached_file_paths': list(self._cache.keys()),
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / 1024 / 1024, 2)
        }
