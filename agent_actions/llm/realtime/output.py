"""Module for handling output data saving operations."""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from agent_actions.errors import AgentActionsError
from agent_actions.output.writer import FileWriter

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
        action_name: str | None = None,
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
        data: list[dict[str, Any]],
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
        output_file_path: Path | None = None
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
        except OSError as e:
            raise AgentActionsError(
                "IOError saving main output",
                context={
                    "output_file_path": str(output_file_path) if output_file_path else "unknown",
                    "file_path": file_path,
                    "operation": "save_main_output",
                },
                cause=e,
            ) from e
        except Exception as e:
            raise AgentActionsError(
                "Error saving main output",
                context={
                    "output_file_path": str(output_file_path) if output_file_path else "unknown",
                    "file_path": file_path,
                    "operation": "save_main_output",
                },
                cause=e,
            ) from e

    def _ensure_directory_exists(self, file_path):
        """Ensure the directory for the file path exists."""
        directory = Path(file_path).parent
        directory.mkdir(parents=True, exist_ok=True)

