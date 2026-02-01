"""
Shared file writing utilities.
"""

import json
import csv
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agent_actions.errors import AgentActionsException  # New modular pattern!
from agent_actions.processing.error_handling import ProcessorErrorHandlerMixin
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    FileWriteStartedEvent,
    FileWriteCompleteEvent,
)

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend


class FileWriter(ProcessorErrorHandlerMixin):
    """
    File writer utility for writing data to various file formats.

    Supports JSON, TXT, and CSV formats with integrated error handling.
    Uses ProcessorErrorHandlerMixin for consistent error reporting.

    Optionally uses a StorageBackend for database-backed persistence.
    """

    def __init__(
        self,
        file_path: str,
        storage_backend: Optional["StorageBackend"] = None,
        node_name: Optional[str] = None,
    ):
        """
        Initialize file writer.

        Args:
            file_path: Path to the output file
            storage_backend: Optional storage backend for database persistence
            node_name: Node name for backend writes (required if storage_backend provided)
        """
        super().__init__()
        self.file_path = file_path
        self.file_type = Path(file_path).suffix.lower()
        self.storage_backend = storage_backend
        self.node_name = node_name

    def write_staging(self, data):
        """
        Write data to staging file in appropriate format.

        Args:
            data: Data to write (format depends on file type)

        Raises:
            AgentActionsException: If file type is unsupported
        """
        try:
            # Fire event before writing
            fire_event(
                FileWriteStartedEvent(
                    file_path=str(self.file_path),
                    file_type=self.file_type,
                )
            )

            with open(self.file_path, "w", encoding="utf-8") as file:
                if self.file_type == ".json":
                    json.dump(data, file, indent=4)
                elif self.file_type == ".txt":
                    if isinstance(data, list):
                        file.write("\n".join(data))
                    else:
                        file.write(data)
                elif self.file_type == ".csv":
                    writer = csv.writer(file)
                    writer.writerows(data)
                else:
                    raise AgentActionsException(
                        f"Unsupported file type for staging: {self.file_type} "
                        f"for file {self.file_path}"
                    )

            # Get file size after writing
            bytes_written = Path(self.file_path).stat().st_size

            # Fire event after writing
            fire_event(
                FileWriteCompleteEvent(
                    file_path=str(self.file_path),
                    file_type=self.file_type,
                    bytes_written=bytes_written,
                )
            )
        except IOError as e:
            self.handle_file_error(e, "write_staging", self.file_path, file_type=self.file_type)
        except Exception as e:
            # Catch-all to delegate all errors to error handler mixin
            self.handle_processing_error(
                e,
                f"Write staging file {self.file_path}",
                file_path=self.file_path,
                file_type=self.file_type,
            )

    def write_target(self, data: List[Dict[str, Any]]) -> None:
        """
        Write data to target file.

        If a storage_backend is configured, writes to SQLite database.
        Otherwise falls back to JSON file.

        Args:
            data: Data to write (list of records)
        """
        try:
            # Fire event before writing
            fire_event(
                FileWriteStartedEvent(
                    file_path=str(self.file_path),
                    file_type=self.file_type,
                )
            )

            # Storage backend is required - no JSON file fallback
            if self.storage_backend is None or self.node_name is None:
                raise ValueError(
                    f"Storage backend not configured for write_target. "
                    f"Configure a storage backend (sqlite, tinydb) in your workflow. "
                    f"File: {self.file_path}"
                )
            relative_path = Path(self.file_path).name
            self.storage_backend.write_target(self.node_name, relative_path, data)
            bytes_written = len(json.dumps(data))

            # Fire event after writing
            fire_event(
                FileWriteCompleteEvent(
                    file_path=str(self.file_path),
                    file_type=self.file_type,
                    bytes_written=bytes_written,
                )
            )
        except IOError as e:
            self.handle_file_error(e, "write_target", self.file_path, file_type=self.file_type)
        except Exception as e:
            # Catch-all to delegate all errors to error handler mixin
            self.handle_processing_error(
                e,
                f"Write target file {self.file_path}",
                file_path=self.file_path,
                file_type=self.file_type,
            )

    def write_source(self, data):
        """
        Write data to source file in JSON format.

        Args:
            data: Data to write as JSON
        """
        try:
            # Fire event before writing
            fire_event(
                FileWriteStartedEvent(
                    file_path=str(self.file_path),
                    file_type=self.file_type,
                )
            )

            with open(self.file_path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)

            # Get file size after writing
            bytes_written = Path(self.file_path).stat().st_size

            # Fire event after writing
            fire_event(
                FileWriteCompleteEvent(
                    file_path=str(self.file_path),
                    file_type=self.file_type,
                    bytes_written=bytes_written,
                )
            )
        except IOError as e:
            self.handle_file_error(e, "write_source", self.file_path, file_type=self.file_type)
        except Exception as e:
            # Catch-all to delegate all errors to error handler mixin
            self.handle_processing_error(
                e,
                f"Write source file {self.file_path}",
                file_path=self.file_path,
                file_type=self.file_type,
            )
