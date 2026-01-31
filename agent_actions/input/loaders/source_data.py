"""Module for loading source data."""

# Broad exceptions are intentionally caught for robust error handling and logging
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agent_actions.config.interfaces import ISourceDataLoader, ProcessingMode
from agent_actions.errors import DependencyError, FileLoadError, FileSystemError
from agent_actions.config.paths import PathManager, PathManagerError

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

# Import will be used after class definition to avoid cyclic import
# (deferred registration pattern)

logger = logging.getLogger(__name__)


class SourceDataLoader(ISourceDataLoader):
    """Handles loading source data (Single Responsibility)."""

    def __init__(
        self,
        agent_name: str,
        path_manager: PathManager,
        storage_backend: Optional["StorageBackend"] = None,
    ):
        """
        Initialize the source data loader.

        Args:
            agent_name: Name of the agent
            path_manager: Required PathManager instance for path operations (must be provided)
            storage_backend: Optional storage backend for database-backed reads

        Raises:
            DependencyError: If path_manager is not provided
        """
        self.agent_name = agent_name
        if path_manager is None:
            raise DependencyError("SourceDataLoader", "path_manager")
        self.path_manager = path_manager
        self.storage_backend = storage_backend

    def supports_async(self) -> bool:
        """Return True as this loader supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode to let system choose."""
        return ProcessingMode.AUTO

    def load_source_data(self, file_path: str) -> List[Dict]:
        """
        Load source data from the source directory or storage backend.

        If a storage_backend is configured, attempts to read from the backend first.
        Falls back to file-based loading if backend read fails or is not configured.

        Args:
            file_path: Path to the file containing processed data

        Returns:
            List of source data items

        Raises:
            IOError: If source data cannot be loaded
        """
        # Derive relative path for both backend and file-based loading
        relative_path = self._derive_source_relative_path(file_path)

        # Try storage backend first if available
        if self.storage_backend is not None and relative_path:
            try:
                return self.storage_backend.read_source(relative_path)
            except FileNotFoundError:
                logger.debug(
                    "Source data not found in backend, falling back to file: %s",
                    relative_path,
                    extra={"agent_name": self.agent_name},
                )
            except Exception as e:
                logger.warning(
                    "Backend read failed, falling back to file: %s",
                    e,
                    extra={"agent_name": self.agent_name, "relative_path": relative_path},
                )

        # Fall back to file-based loading
        return self._load_source_from_file(file_path)

    def _derive_source_relative_path(self, file_path: str) -> Optional[str]:
        """
        Derive the relative path for source data from a target file path.

        Args:
            file_path: Path to the target file

        Returns:
            Relative path suitable for backend lookup, or None if derivation fails
        """
        try:
            target_path = self.path_manager.normalize_path(file_path)
            parts = target_path.parts
            agent_io_index = parts.index("agent_io")
            # Skip past agent_io/target/NODE_NAME/ to get the file parts
            file_parts = parts[agent_io_index + 3:]
            if file_parts:
                # Remove .json extension for backend key
                relative = str(Path(*file_parts))
                if relative.endswith(".json"):
                    relative = relative[:-5]
                return relative
        except (ValueError, IndexError) as e:
            logger.debug("Could not derive relative path from agent_io structure: %s", e)
            # Fallback: use just the filename (for temp files from storage backend)
            # This handles cases where data is read from SQLite and processed via temp files
            try:
                filename = Path(file_path).stem  # filename without extension
                if filename:
                    return filename
            except Exception:
                pass
        return None

    def _load_source_from_file(self, file_path: str) -> List[Dict]:
        """
        Load source data from file system.

        This is the original file-based loading logic.
        """
        source_file_to_load = None
        try:
            target_path = self.path_manager.normalize_path(file_path)
            parts = target_path.parts
            try:
                agent_io_index = parts.index("agent_io")
                if len(parts) <= agent_io_index + 1 or parts[agent_io_index + 1] != "target":
                    raise ValueError
            except ValueError as exc:
                raise PathManagerError(f"'agent_io' not found in path {file_path}") from exc
            node_part = parts[agent_io_index + 2] if len(parts) > agent_io_index + 2 else None
            if node_part is None or Path(node_part).suffix:
                error_msg = "Path too short - missing node directory after 'agent_io/target/'"
                error_context = {
                    "file_path": file_path,
                    "agent_name": self.agent_name,
                    "operation": "load_source_data",
                }
                raise FileSystemError(error_msg, context=error_context)
            file_parts = parts[agent_io_index + 3:]
            if not file_parts:
                error_context = {
                    "file_path": file_path,
                    "agent_name": self.agent_name,
                    "operation": "load_source_data",
                }
                raise FileSystemError(
                    "No filename found after node directory", context=error_context
                )
            pipeline_parts = parts[:agent_io_index]
            source_file_to_load = Path(*pipeline_parts) / "agent_io" / "source" / Path(*file_parts)
            if not source_file_to_load.exists():
                raise FileNotFoundError(f"Source file not found: {source_file_to_load}")
            try:
                within_project = self.path_manager.is_within_project(source_file_to_load)
            except Exception as e:
                logger.debug(
                    "Could not verify if source file is within project bounds, assuming valid: %s",
                    e,
                    extra={
                        "source_file": str(source_file_to_load),
                        "agent_name": self.agent_name,
                        "operation": "path_validation",
                    },
                )
                within_project = True
            if not within_project:
                error_context = {
                    "source_file": str(source_file_to_load),
                    "agent_name": self.agent_name,
                    "operation": "load_source_data",
                }
                raise FileSystemError(
                    "Source file is outside project bounds", context=error_context
                )
            with open(source_file_to_load, "r", encoding="utf-8") as file:
                return json.load(file)
        except PathManagerError as e:
            error_context = {
                "file_path": file_path,
                "agent_name": self.agent_name,
                "operation": "load_source_data",
            }
            raise FileSystemError(
                "Path structure error when deriving source", context=error_context, cause=e
            ) from e
        except Exception as e:
            error_context = {
                "source_file": str(source_file_to_load) if source_file_to_load else "unknown",
                "input_file_path": file_path,
                "agent_name": self.agent_name,
                "operation": "load_source_data",
                "suggestion": (
                    "Check if the source file exists and has valid JSON/YAML format. "
                    "Verify file permissions."
                ),
            }
            raise FileLoadError("Failed to load source data", context=error_context, cause=e) from e

    def save_source_data(self, file_path: str, source_guid: str, content: Dict) -> None:
        """
        Save source data to the source directory.

        Args:
            file_path: Path to the file containing processed data
            source_guid: source_guid to associate with the content
            content: Content to save
        """
        try:
            target_path = self.path_manager.normalize_path(file_path)
            parts = target_path.parts
            try:
                agent_io_index = parts.index("agent_io")
            except ValueError as exc:
                raise PathManagerError(f"'agent_io' not found in path {file_path}") from exc
            pipeline_parts = parts[:agent_io_index]
            source_dir = Path(*pipeline_parts) / "agent_io" / "source"
            source_dir.mkdir(parents=True, exist_ok=True)
            source_file = source_dir / f"{source_guid}.json"
            with open(source_file, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2)
        except Exception as e:
            error_context = {
                "source_guid": source_guid,
                "file_path": file_path,
                "agent_name": self.agent_name,
                "operation": "save_source_data",
            }
            raise FileLoadError("Failed to save source data", context=error_context, cause=e) from e

    def load_source_content(self, file_path: str, context_data: Dict[str, Any]) -> Optional[Any]:
        """
        Load specific content from source file by source_guid.

        Args:
            file_path: Path to the file containing processed data
            context_data: Context data containing source_guid

        Returns:
            Optional[Any]: Loaded content or None if not found
        """
        try:
            source_guid = context_data.get("source_guid")
            if not source_guid:
                return None
            source_data = self.load_source_data(file_path)
            for item in source_data:
                if item.get("source_guid") == source_guid:
                    # Support both legacy wrapped content and new flat content
                    if "content" in item and isinstance(item["content"], dict):
                        return item.get("content")
                    return item
            return None
        except Exception as e:
            logger.warning(
                "Failed to load source content for source_guid %s from %s: %s",
                context_data.get("source_guid"),
                file_path,
                e,
                exc_info=True,
                extra={
                    "source_guid": context_data.get("source_guid"),
                    "file_path": file_path,
                    "agent_name": self.agent_name,
                    "operation": "load_source_content",
                },
            )
            return None
