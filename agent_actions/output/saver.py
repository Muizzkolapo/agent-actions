"""Unified source data saving using storage backend."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    SourceDataSavedEvent,
    SourceDataSavingEvent,
)

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class UnifiedSourceDataSaver:
    """Saves source data to a storage backend with optional deduplication."""

    def __init__(
        self,
        base_directory: str,
        enable_deduplication: bool = True,
        storage_backend: StorageBackend | None = None,
    ):
        self.base_directory = Path(base_directory)
        self.enable_deduplication = enable_deduplication
        self.storage_backend = storage_backend

    def save_source_items(self, items: dict | list[dict], relative_path: str) -> None:
        """Save source data to storage backend with optional deduplication.

        Args:
            relative_path: Relative path for source file (e.g., 'node_1_Agent/batch_001')

        Raises:
            ValueError: If storage_backend is not configured
        """
        if isinstance(items, dict):
            items = [items]

        destination = f"source data for {relative_path}"

        logger.debug(
            "Saving %d source items as %s (dedup=%s, backend=%s)",
            len(items),
            destination,
            self.enable_deduplication,
            self.storage_backend is not None,
        )

        if self.storage_backend is None:
            raise ValueError(
                f"Storage backend not configured for write_source. "
                f"Configure a storage backend (sqlite, tinydb) in your workflow. "
                f"Path: {relative_path}"
            )

        fire_event(
            SourceDataSavingEvent(
                file_path=destination,
                item_count=len(items),
            )
        )

        self.storage_backend.write_source(
            relative_path, items, enable_deduplication=self.enable_deduplication
        )
        bytes_written = sum(len(json.dumps(item, default=str).encode()) for item in items)

        fire_event(
            SourceDataSavedEvent(
                file_path=destination,
                item_count=len(items),
                bytes_written=bytes_written,
            )
        )

        logger.info("Saved %d source items as %s", len(items), destination)
