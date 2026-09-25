"""Unified source data saving using storage backend."""

from __future__ import annotations

import json
import logging
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
        enable_deduplication: bool = True,
        storage_backend: StorageBackend | None = None,
    ):
        self.enable_deduplication = enable_deduplication
        self.storage_backend = storage_backend

    def save_source_items(self, items: dict | list[dict], relative_path: str) -> None:
        """Save source data to the storage backend, optionally deduplicated.

        *relative_path* is the key the store records these items under
        ('node_1_Agent/batch_001'), not a location on disk — nothing here writes
        a file.
        """
        if isinstance(items, dict):
            items = [items]

        logger.debug(
            "Saving %d source items under %s (dedup=%s, backend=%s)",
            len(items),
            relative_path,
            self.enable_deduplication,
            self.storage_backend is not None,
        )

        if self.storage_backend is None:
            raise ValueError(
                f"Storage backend not configured for write_source. "
                f"Configure a storage backend (sqlite) in your workflow. "
                f"Path: {relative_path}"
            )

        fire_event(
            SourceDataSavingEvent(
                relative_path=relative_path,
                item_count=len(items),
            )
        )

        self.storage_backend.write_source(
            relative_path, items, enable_deduplication=self.enable_deduplication
        )
        bytes_written = sum(len(json.dumps(item, default=str).encode()) for item in items)

        fire_event(
            SourceDataSavedEvent(
                relative_path=relative_path,
                item_count=len(items),
                bytes_written=bytes_written,
            )
        )

        logger.info("Saved %d source items under %s", len(items), relative_path)
