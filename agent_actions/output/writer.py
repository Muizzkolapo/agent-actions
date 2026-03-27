"""Shared file writing utilities."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_actions.errors import AgentActionsError
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    FileWriteCompleteEvent,
    FileWriteStartedEvent,
)
from agent_actions.processing.error_handling import ProcessorErrorHandlerMixin

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend


class FileWriter(ProcessorErrorHandlerMixin):
    """Writes data to JSON, TXT, or CSV files with optional storage backend persistence."""

    def __init__(
        self,
        file_path: str,
        storage_backend: StorageBackend | None = None,
        action_name: str | None = None,
        output_directory: str | None = None,
    ):
        """Initialize file writer.

        Args:
            action_name: Node name for backend writes (required if storage_backend provided)
            output_directory: Base directory for computing relative paths (preserves subdirs)
        """
        super().__init__()
        self.file_path = file_path
        self.file_type = Path(file_path).suffix.lower()
        self.storage_backend = storage_backend
        self.action_name = action_name
        self.output_directory = output_directory

    def _execute_write(self, operation_name: str, write_fn: Callable[[], int]) -> None:
        """Execute a write operation with event firing and error handling."""
        try:
            fire_event(
                FileWriteStartedEvent(
                    file_path=str(self.file_path),
                    file_type=self.file_type,
                )
            )

            bytes_written = write_fn()

            fire_event(
                FileWriteCompleteEvent(
                    file_path=str(self.file_path),
                    file_type=self.file_type,
                    bytes_written=bytes_written,
                )
            )
        except OSError as e:
            self.handle_file_error(e, operation_name, self.file_path, file_type=self.file_type)
        except Exception as e:
            self.handle_processing_error(
                e,
                f"{operation_name} {self.file_path}",
                file_path=self.file_path,
                file_type=self.file_type,
            )

    def write_staging(self, data: Any) -> None:
        """Write data to staging file in appropriate format.

        Raises:
            AgentActionsError: If file type is unsupported
        """

        def do_write() -> int:
            Path(self.file_path).parent.mkdir(parents=True, exist_ok=True)
            if self.file_type == ".json":
                dir_path = os.path.dirname(self.file_path) or "."
                fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as file:
                        json.dump(data, file, indent=4)
                    os.replace(tmp_path, self.file_path)
                except BaseException:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
            elif self.file_type == ".txt":
                with open(self.file_path, "w", encoding="utf-8") as file:
                    if isinstance(data, list):
                        file.write("\n".join(data))
                    else:
                        file.write(data)
            elif self.file_type == ".csv":
                with open(self.file_path, "w", encoding="utf-8", newline="") as file:
                    if data and isinstance(data[0], dict):
                        writer = csv.DictWriter(file, fieldnames=data[0].keys())
                        writer.writeheader()
                        writer.writerows(data)
                    else:
                        writer = csv.writer(file)  # type: ignore[assignment]
                        writer.writerows(data)
            else:
                raise AgentActionsError(
                    f"Unsupported file type for staging: {self.file_type} for file {self.file_path}"
                )
            return Path(self.file_path).stat().st_size

        self._execute_write("Write staging file", do_write)

    def write_target(self, data: list[dict[str, Any]]) -> None:
        """Write data to target via storage backend (raises ValueError if backend is missing)."""

        def do_write() -> int:
            if self.storage_backend is None or self.action_name is None:
                raise ValueError(
                    f"Storage backend not configured for write_target. "
                    f"Configure a storage backend (sqlite, tinydb) in your workflow. "
                    f"File: {self.file_path}"
                )
            file_path = Path(self.file_path)
            if self.output_directory:
                try:
                    relative_path = str(file_path.relative_to(self.output_directory))
                except ValueError:
                    relative_path = file_path.name
            else:
                relative_path = file_path.name
            self.storage_backend.write_target(self.action_name, relative_path, data)
            return len(json.dumps(data))

        self._execute_write("Write target file", do_write)

    def write_source(self, data: Any) -> None:
        """Write data to source file in JSON format."""

        def do_write() -> int:
            Path(self.file_path).parent.mkdir(parents=True, exist_ok=True)
            dir_path = os.path.dirname(self.file_path) or "."
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    json.dump(data, file, indent=4)
                os.replace(tmp_path, self.file_path)
            except BaseException:
                os.unlink(tmp_path)
                raise
            return Path(self.file_path).stat().st_size

        self._execute_write("Write source file", do_write)
