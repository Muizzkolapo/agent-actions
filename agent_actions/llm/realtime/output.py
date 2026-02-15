"""Module for handling output data saving operations."""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agent_actions.output.writer import FileWriter
from agent_actions.errors import AgentActionsException

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend


class OutputHandler:
    """
    Responsible for saving output data to appropriate locations.

    Optionally uses a StorageBackend for database-backed persistence.
    """

    def __init__(
        self,
        storage_backend: Optional["StorageBackend"] = None,
        action_name: Optional[str] = None,
    ):
        """
        Initialize output handler.

        Args:
            storage_backend: Optional storage backend for database persistence
            action_name: Node name for backend writes (required if storage_backend provided)
        """
        self.storage_backend = storage_backend
        self.action_name = action_name

    def save_main_output(
        self,
        data: List[Dict[str, Any]],
        file_path: str,
        base_directory: str,
        output_directory: str,
    ) -> None:
        """
        Save main output data to the output directory.

        If a storage_backend is configured, writes to the backend instead.

        Args:
            data: Data to save (list of records)
            file_path: Path to the input file
            base_directory: Base directory for calculating relative paths
            output_directory: Directory where the output file will be saved
        """
        try:
            relative_path = Path(file_path).relative_to(base_directory)
            output_file_path = Path(output_directory) / relative_path
            # Only create directory if not using storage backend
            if self.storage_backend is None:
                self._ensure_directory_exists(str(output_file_path))
            file_writer = FileWriter(
                str(output_file_path),
                storage_backend=self.storage_backend,
                action_name=self.action_name,
                output_directory=output_directory,
            )
            file_writer.write_target(data)
        except IOError as e:
            raise AgentActionsException(
                "IOError saving main output",
                context={
                    "output_file_path": str(output_file_path),
                    "file_path": file_path,
                    "operation": "save_main_output",
                },
                cause=e,
            )
        except Exception as e:
            raise AgentActionsException(
                "Error saving main output",
                context={
                    "output_file_path": str(output_file_path),
                    "file_path": file_path,
                    "operation": "save_main_output",
                },
                cause=e,
            )

    def _ensure_directory_exists(self, file_path):
        """Ensure the directory for the file path exists."""
        directory = Path(file_path).parent
        directory.mkdir(parents=True, exist_ok=True)

    def _load_existing_content(self, file_path):
        """Load existing content from file if it exists."""
        if Path(file_path).exists():
            with open(file_path, "r", encoding="utf-8") as file:
                try:
                    existing_content = json.load(file)
                except json.JSONDecodeError:
                    existing_content = []
        else:
            existing_content = []
        if not isinstance(existing_content, list):
            existing_content = [existing_content]
        return existing_content
