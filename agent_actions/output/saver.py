"""Unified source data saving using storage backend."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    SourceDataSavedEvent,
    SourceDataSavingEvent,
)

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class UnifiedSourceDataSaver:
    """Unified source data saver using storage backend.

    Requires a StorageBackend for database-backed persistence.
    No JSON file fallback - configure sqlite or tinydb backend.
    """

    def __init__(
        self,
        base_directory: str,
        enable_deduplication: bool = True,
        enable_locking: bool = True,  # Deprecated, kept for API compatibility
        storage_backend: StorageBackend | None = None,
    ):
        """Initialize unified source data saver.

        Args:
            base_directory: Base directory for workflow (e.g., '/path/to/workflow')
            enable_deduplication: Whether to deduplicate by source_guid (default: True)
            enable_locking: Deprecated - storage backend handles concurrency (ignored)
            storage_backend: Storage backend for database persistence (required)
        """
        self.base_directory = Path(base_directory)
        self.enable_deduplication = enable_deduplication
        self.storage_backend = storage_backend
        del enable_locking  # Explicitly unused - storage backend handles concurrency

    def save_source_items(self, items: dict | list[dict], relative_path: str) -> None:
        """Save source data to storage backend with optional deduplication.

        Args:
            items: Single item or list of items with source_guid
            relative_path: Relative path for source file (e.g., 'node_1_Agent/batch_001')

        Raises:
            ValueError: If storage_backend is not configured
        """
        # Normalize to list
        if isinstance(items, dict):
            items = [items]

        # Build source file path (for logging/events even when using backend)
        source_dir = self.base_directory / "agent_io" / "source"
        source_file = source_dir / f"{relative_path}.json"

        logger.debug(
            "Saving %d source items to %s (dedup=%s, backend=%s)",
            len(items),
            source_file,
            self.enable_deduplication,
            self.storage_backend is not None,
        )

        fire_event(
            SourceDataSavingEvent(
                file_path=str(source_file),
                item_count=len(items),
            )
        )

        if self.storage_backend is None:
            raise ValueError(
                f"Storage backend not configured for write_source. "
                f"Configure a storage backend (sqlite, tinydb) in your workflow. "
                f"File: {source_file}"
            )

        self.storage_backend.write_source(
            relative_path, items, enable_deduplication=self.enable_deduplication
        )
        bytes_written = sum(len(json.dumps(item)) for item in items)

        fire_event(
            SourceDataSavedEvent(
                file_path=str(source_file),
                item_count=len(items),
                bytes_written=bytes_written,
            )
        )

        logger.info("Saved %d source items to %s", len(items), source_file)
