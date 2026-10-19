"""Static Data Loader for external reference files in context_scope configuration."""
# Line-too-long: Descriptive error messages and contexts require long lines
# Unused-argument: Interface consistency for _parse_file_path method
# No-else-return: Code clarity - explicit return paths for different file types
# Import-outside-toplevel: Import sys only when needed in get_cache_stats

import csv
import json
import logging
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from agent_actions.config.defaults import SeedDataDefaults
from agent_actions.config.path_config import SeedFileError, SeedFolder, resolve_seed_file
from agent_actions.errors import ConfigurationError, FileSystemError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.cache_events import (
    CacheHitEvent,
    CacheInvalidationEvent,
    CacheMissEvent,
)
from agent_actions.prompt.context.seed_entry import SeedSelectionError, parse_seed_entry

logger = logging.getLogger(__name__)


class StaticDataLoadError(FileSystemError):
    """Exception raised during static data loading."""

    def __init__(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        *,
        cause: Exception | None = None,
    ):
        """Initialize StaticDataLoadError with message, context, and optional cause."""
        ctx = context or {}
        ctx["operation"] = "load_static_data"
        super().__init__(message, context=ctx, cause=cause)


class StaticDataLoader:
    """Loads static/seed data files with caching and path validation."""

    # File size limit to prevent memory issues
    MAX_FILE_SIZE_BYTES = SeedDataDefaults.MAX_FILE_SIZE_BYTES

    # Supported file extensions
    SUPPORTED_EXTENSIONS = {".json", ".yml", ".yaml", ".md", ".txt", ".csv"}

    def __init__(self, static_data_dir: Path | Sequence[SeedFolder]):
        """The folders a reference is looked for in, in order; one path is a list of one."""
        if isinstance(static_data_dir, Path):
            if not static_data_dir.exists():
                raise ValueError(f"Static data directory does not exist: {static_data_dir}")
            if not static_data_dir.is_dir():
                raise ValueError(f"Static data path is not a directory: {static_data_dir}")
            resolved = static_data_dir.resolve()
            folders = [SeedFolder(resolved, "workflow", resolved.name)]
        else:
            folders = list(static_data_dir)
            if not folders:
                raise ValueError("No seed folder to load from")

        self.folders = folders
        self.static_data_dir = folders[0].path
        self._cache: dict[str, Any] = {}

        logger.debug(
            "StaticDataLoader initialized with folders: %s", [str(f.path) for f in folders]
        )

    def load_static_data(
        self,
        static_data_config: Mapping[str, Any],
        *,
        source: Mapping[str, Any] | None = None,
        action_name: str = "",
    ) -> dict[str, Any]:
        """Load the seed files of ``context_scope.seed`` for one record.

        ``source`` is the record's own fields; an entry that selects its file by one
        of them reads it here, so the selector never has to appear in the prompt.
        """
        if not static_data_config:
            logger.debug("No static data config provided, skipping load")
            return {}

        loaded_data = {}

        for field_name, raw_entry in static_data_config.items():
            try:
                entry = parse_seed_entry(field_name, raw_entry, action_name)
                file_spec = entry.file_for(source, action_name)
                file_path = self._parse_file_path(file_spec, field_name)

                # Resolve and validate path
                resolved_path = self._resolve_path(file_path, field_name)

                # Check cache. The file's size and mtime are in the key, so a shared
                # loader re-reads a file that changed.
                try:
                    stat = resolved_path.stat()
                    cache_key = f"{resolved_path}:{stat.st_mtime_ns}:{stat.st_size}"
                except OSError:
                    cache_key = str(resolved_path)
                if cache_key in self._cache:
                    logger.debug("Cache hit for field '%s': %s", field_name, cache_key)
                    fire_event(CacheHitEvent(cache_type="static_data", key=field_name))
                    loaded_data[field_name] = self._cache[cache_key]
                else:
                    # Load and cache
                    logger.debug("Loading file for field '%s': %s", field_name, resolved_path)
                    fire_event(
                        CacheMissEvent(
                            cache_type="static_data", key=field_name, reason="file not in cache"
                        )
                    )
                    data = self._load_file(resolved_path, field_name)
                    self._cache[cache_key] = data
                    loaded_data[field_name] = data
                    logger.debug(
                        "Loaded static data field '%s' from %s", field_name, resolved_path.name
                    )

            except SeedSelectionError as e:
                raise StaticDataLoadError(
                    str(e),
                    context={
                        "field_name": field_name,
                        "select_by": entry.select_by,
                        "error_type": "seed_value_not_selectable",
                    },
                    cause=e,
                ) from e
            except (StaticDataLoadError, ConfigurationError):
                raise
            except Exception as e:
                # Wrap unexpected errors
                logger.error("Unexpected error loading field '%s': %s", field_name, e)
                raise StaticDataLoadError(
                    f"Failed to load static data field '{field_name}': {str(e)}",
                    context={
                        "field_name": field_name,
                        "file_spec": str(raw_entry),
                        "error_type": "unexpected_error",
                    },
                    cause=e,
                ) from e

        logger.debug("Loaded %s static data fields: %s", len(loaded_data), list(loaded_data.keys()))
        return loaded_data

    def _parse_file_path(self, file_spec: str, field_name: str) -> str:
        """Parse file path from $file: prefix syntax."""
        if file_spec.startswith("$file:"):
            return file_spec[6:]  # Remove '$file:' prefix
        return file_spec  # Use as-is

    def _resolve_path(self, file_path: str, field_name: str) -> Path:
        """The file *file_path* names, from the first folder that holds it.

        Traversal prevention is the shared ``resolve_seed_file`` rule; any failure
        is wrapped in a ``StaticDataLoadError`` with context for diagnostics.
        """
        path = Path(file_path)

        # Reject absolute paths immediately
        if path.is_absolute():
            logger.error("Absolute path rejected for field '%s': %s", field_name, file_path)
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Absolute paths not allowed",
                context={
                    "field_name": field_name,
                    "file_path": file_path,
                    "error_type": "absolute_path_not_allowed",
                    "static_data_dir": str(self.static_data_dir),
                },
            )

        try:
            found = resolve_seed_file(file_path, self.folders)
        except SeedFileError as exc:
            not_found = str(exc).startswith("Seed file not found")
            raise StaticDataLoadError(
                f"Static data field '{field_name}': "
                + ("File not found. " if not_found else "")
                + str(exc),
                context={
                    "field_name": field_name,
                    "file_path": file_path,
                    "searched": [str(folder.path) for folder in self.folders],
                    "error_type": "file_not_found" if not_found else "seed_file_in_two_folders",
                },
            ) from exc
        except ValueError as exc:
            logger.error(
                "Path traversal attempt detected for field '%s': %s",
                field_name,
                file_path,
            )
            raise StaticDataLoadError(
                f"Static data field '{field_name}': File path escapes static data directory",
                context={
                    "field_name": field_name,
                    "original_path": file_path,
                    "static_data_dir": str(self.static_data_dir),
                    "error_type": "path_traversal_attempt",
                },
            ) from exc

        logger.debug("Resolved path for field '%s': %s", field_name, found.path)
        return found.path

    def _load_file(self, file_path: Path, field_name: str) -> Any:
        return self.parse_file(file_path, field_name)

    @classmethod
    def parse_file(cls, file_path: Path, field_name: str) -> Any:
        """Parse one seed file by its extension, as the run reads it.

        Pre-flight calls this too, so the two cannot disagree on what a seed file holds.
        """
        # Check if file exists
        if not file_path.exists():
            raise StaticDataLoadError(
                f"Static data field '{field_name}': File not found",
                context={
                    "field_name": field_name,
                    "file_path": str(file_path),
                    "error_type": "file_not_found",
                },
            )

        # Check file size
        file_size = file_path.stat().st_size
        if file_size > cls.MAX_FILE_SIZE_BYTES:
            raise StaticDataLoadError(
                f"Static data field '{field_name}': File too large "
                f"({file_size / 1024 / 1024:.2f}MB, max {cls.MAX_FILE_SIZE_BYTES / 1024 / 1024}MB)",
                context={
                    "field_name": field_name,
                    "file_path": str(file_path),
                    "file_size_bytes": file_size,
                    "max_size_bytes": cls.MAX_FILE_SIZE_BYTES,
                    "error_type": "file_too_large",
                },
            )

        # Dispatch to format-specific loader
        suffix = file_path.suffix.lower()

        if suffix == ".json":
            return cls._load_json(file_path, field_name)
        elif suffix in {".yml", ".yaml"}:
            return cls._load_yaml(file_path, field_name)
        elif suffix in {".md", ".txt"}:
            return cls._load_text(file_path, field_name)
        elif suffix == ".csv":
            return cls._load_csv(file_path, field_name)
        else:
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Unsupported file type '{suffix}'",
                context={
                    "field_name": field_name,
                    "file_path": str(file_path),
                    "file_type": suffix,
                    "supported_types": list(cls.SUPPORTED_EXTENSIONS),
                    "error_type": "unsupported_format",
                },
            )

    @staticmethod
    def _load_json(file_path: Path, field_name: str) -> Any:
        """Load and parse JSON file."""
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error("JSON parse error in field '%s': %s", field_name, e)
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Invalid JSON format",
                context={
                    "field_name": field_name,
                    "file_path": str(file_path),
                    "parse_error": str(e),
                    "line": e.lineno if hasattr(e, "lineno") else None,
                    "column": e.colno if hasattr(e, "colno") else None,
                    "error_type": "json_parse_error",
                },
                cause=e,
            ) from e
        except Exception as e:
            logger.error("Error reading JSON file for field '%s': %s", field_name, e)
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Failed to read JSON file",
                context={
                    "field_name": field_name,
                    "file_path": str(file_path),
                    "error": str(e),
                    "error_type": "json_read_error",
                },
                cause=e,
            ) from e

    @staticmethod
    def _load_yaml(file_path: Path, field_name: str) -> Any:
        """Load and parse YAML file."""
        try:
            with open(file_path, encoding="utf-8") as f:
                return yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.error("YAML parse error in field '%s': %s", field_name, e)
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Invalid YAML format",
                context={
                    "field_name": field_name,
                    "file_path": str(file_path),
                    "parse_error": str(e),
                    "error_type": "yaml_parse_error",
                },
                cause=e,
            ) from e
        except Exception as e:
            logger.error("Error reading YAML file for field '%s': %s", field_name, e)
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Failed to read YAML file",
                context={
                    "field_name": field_name,
                    "file_path": str(file_path),
                    "error": str(e),
                    "error_type": "yaml_read_error",
                },
                cause=e,
            ) from e

    @staticmethod
    def _load_text(file_path: Path, field_name: str) -> str:
        """Load plain text or Markdown file."""
        try:
            with open(file_path, encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error("Error reading text file for field '%s': %s", field_name, e)
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Failed to read text file",
                context={
                    "field_name": field_name,
                    "file_path": str(file_path),
                    "error": str(e),
                    "error_type": "text_read_error",
                },
                cause=e,
            ) from e

    @staticmethod
    def _load_csv(file_path: Path, field_name: str) -> list:
        """Load CSV file as list of dictionaries with headers as keys."""
        try:
            # utf-8-sig keeps a byte order mark out of the first key; newline="" keeps
            # a quoted \r\n as written.
            with open(file_path, encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                return list(reader)
        except csv.Error as e:
            logger.error("CSV parse error in field '%s': %s", field_name, e)
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Invalid CSV format",
                context={
                    "field_name": field_name,
                    "file_path": str(file_path),
                    "parse_error": str(e),
                    "error_type": "csv_parse_error",
                },
                cause=e,
            ) from e
        except Exception as e:
            logger.error("Error reading CSV file for field '%s': %s", field_name, e)
            raise StaticDataLoadError(
                f"Static data field '{field_name}': Failed to read CSV file",
                context={
                    "field_name": field_name,
                    "file_path": str(file_path),
                    "error": str(e),
                    "error_type": "csv_read_error",
                },
                cause=e,
            ) from e

    def clear_cache(self) -> None:
        """Clear the file cache."""
        num_files = len(self._cache)
        self._cache.clear()
        logger.debug("Cache cleared (%s files removed)", num_files)

        # Fire cache invalidation event
        fire_event(
            CacheInvalidationEvent(
                cache_type="static_data", entries_removed=num_files, reason="manual clear"
            )
        )

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics for debugging."""
        import sys

        # Estimate cache size
        total_size = sum(sys.getsizeof(value) for value in self._cache.values())

        return {
            "cached_files": len(self._cache),
            "cached_file_paths": list(self._cache.keys()),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
        }


_SHARED_LOADERS: dict[tuple[tuple[Path, str], ...], StaticDataLoader] = {}
_SHARED_LOADERS_LOCK = threading.Lock()


def shared_static_data_loader(static_data_dir: Path | Sequence[SeedFolder]) -> StaticDataLoader:
    """One loader per folder list for the process, so a file is parsed once.

    What it returns is shared between callers: read it, never write to it. One
    path is a list of one folder, as for ``StaticDataLoader`` itself.
    """
    if isinstance(static_data_dir, Path):
        resolved = static_data_dir.resolve()
        folders: list[SeedFolder] = [SeedFolder(resolved, "workflow", resolved.name)]
    else:
        folders = list(static_data_dir)
    # The kind is part of the key: the same folder is the workflow's own in one list and
    # a shared one in another, and the resolver's rules differ between the two.
    key = tuple((folder.path, folder.kind) for folder in folders)
    with _SHARED_LOADERS_LOCK:
        loader = _SHARED_LOADERS.get(key)
        if loader is None:
            loader = StaticDataLoader(folders)
            _SHARED_LOADERS[key] = loader
        return loader
