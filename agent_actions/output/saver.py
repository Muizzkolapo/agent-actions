"""
Unified source data saving across batch and online modes.
"""

import json
import logging
from enum import Enum
from typing import List, Dict, Union, TYPE_CHECKING, Optional
from pathlib import Path

from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    SourceDataSavingEvent,
    SourceDataSavedEvent,
)

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class SourceSaveMode(Enum):
    """Source data save modes."""

    BATCH = "batch"  # Array format with deduplication
    ONLINE = "online"  # Standard mode


class UnifiedSourceDataSaver:
    """
    Unified source data saver using storage backend.

    Requires a StorageBackend for database-backed persistence.
    No JSON file fallback - configure sqlite or tinydb backend.

    Note: Single public method by design - focused utility class.
    """

    def __init__(
        self,
        base_directory: str,
        enable_deduplication: bool = True,
        enable_locking: bool = True,  # Kept for API compatibility, ignored
        storage_backend: Optional["StorageBackend"] = None,
    ):
        """
        Initialize unified source data saver.

        Args:
            base_directory: Base directory for workflow (e.g., '/path/to/workflow')
            enable_deduplication: Whether to deduplicate by source_guid (default: True)
            enable_locking: Deprecated - storage backend handles concurrency
            storage_backend: Storage backend for database persistence (required)

        Raises:
            ValueError: If storage_backend is not configured when save_source_items is called
        """
        self.base_directory = Path(base_directory)
        self.enable_deduplication = enable_deduplication
        self.storage_backend = storage_backend
        # Locking not needed - storage backend handles concurrency
        _ = enable_locking  # Suppress unused parameter warning

    def save_source_items(self, items: Union[Dict, List[Dict]], relative_path: str) -> None:
        """
        Save source data with optional deduplication and locking.

        This method handles the complete source saving workflow:
        1. Normalize items to list
        2. Build source file path
        3. Load existing items (if file exists)
        4. Deduplicate by source_guid (if enabled)
        5. Merge and save

        If a storage_backend is configured, writes to the backend instead.

        Args:
            items: Single item or list of items with source_guid
            relative_path: Relative path for source file (e.g., 'node_1_Agent/batch_001')

        File structure: {base_directory}/agent_io/source/{relative_path}.json
        Format: JSON array of items with source_guid deduplication

        Example:
            >>> saver = UnifiedSourceDataSaver('/workflow', enable_locking=True)
            >>> saver.save_source_items(
            ...     items=[{'source_guid': 'guid1', 'content': {'data': 'test'}}],
            ...     relative_path='node_1_Agent/batch_001'
            ... )
            # Saves to: /workflow/agent_io/source/node_1_Agent/batch_001.json

        Raises:
            IOError: If file operations fail
            json.JSONDecodeError: If existing file contains invalid JSON
        """
        # Normalize to list
        if isinstance(items, dict):
            items = [items]

        # Build source file path (for logging/events even when using backend)
        source_dir = self.base_directory / "agent_io" / "source"
        source_file = source_dir / f"{relative_path}.json"

        logger.debug(
            "Saving %d source items to %s (dedup=%s, lock=%s, backend=%s)",
            len(items),
            source_file,
            self.enable_deduplication,
            self.enable_locking,
            self.storage_backend is not None,
        )

        # Fire event before saving
        fire_event(
            SourceDataSavingEvent(
                file_path=str(source_file),
                item_count=len(items),
            )
        )

        # Storage backend is required - no JSON file fallback
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

        # Fire event after saving
        fire_event(
            SourceDataSavedEvent(
                file_path=str(source_file),
                item_count=len(items),
                bytes_written=bytes_written,
            )
        )

        logger.info("Saved %d source items to %s", len(items), source_file)

# Convenience function for getting saver instance
def get_source_data_saver(
    base_directory: str,
    mode: SourceSaveMode = SourceSaveMode.BATCH,
    storage_backend: Optional["StorageBackend"] = None,
) -> UnifiedSourceDataSaver:
    """
    Get UnifiedSourceDataSaver instance with mode-specific defaults.

    Args:
        base_directory: Base directory for workflow
        mode: Save mode (BATCH or ONLINE)
        storage_backend: Optional storage backend for database persistence

    Returns:
        UnifiedSourceDataSaver configured for the specified mode

    Example:
        >>> # Batch mode (locking + deduplication)
        >>> saver = get_source_data_saver('/workflow', SourceSaveMode.BATCH)

        >>> # Online mode (no locking)
        >>> saver = get_source_data_saver('/workflow', SourceSaveMode.ONLINE)

        >>> # With storage backend
        >>> backend = get_storage_backend('/workflow', 'my_workflow')
        >>> saver = get_source_data_saver('/workflow', storage_backend=backend)
    """
    if mode == SourceSaveMode.BATCH:
        return UnifiedSourceDataSaver(
            base_directory=base_directory,
            enable_deduplication=True,
            enable_locking=True,
            storage_backend=storage_backend,
        )
    # ONLINE mode
    return UnifiedSourceDataSaver(
        base_directory=base_directory,
        enable_deduplication=True,
        enable_locking=False,  # Online is single-threaded
        storage_backend=storage_backend,
    )
