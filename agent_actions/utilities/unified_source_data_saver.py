"""
Unified source data saving across batch and online modes.

This module consolidates source data saving logic that was duplicated across:
- Batch mode: batch_service.py (_save_task_source method)
- Online mode: extractors_source_data_loader.py + source_path_manager.py

## Overview

UnifiedSourceDataSaver provides a single interface for saving source data with
configurable deduplication and file locking strategies.

## Usage

**Batch Mode** (with locking and deduplication):
```python
from agent_actions.utilities.unified_source_data_saver import UnifiedSourceDataSaver

saver = UnifiedSourceDataSaver(
    base_directory='/path/to/workflow',
    enable_deduplication=True,
    enable_locking=True
)

# Save source items
saver.save_source_items(
    items=[{'source_guid': 'guid1', 'content': {...}}],
    relative_path='node_1_Agent/batch_001'
)
```

**Online Mode** (without locking):
```python
saver = UnifiedSourceDataSaver(
    base_directory='/path/to/workflow',
    enable_deduplication=True,
    enable_locking=False  # Online mode doesn't need locking (single-threaded)
)

saver.save_source_items(
    items=[{'source_guid': 'guid1', 'content': {...}}],
    relative_path='node_1_Agent/online_001'
)
```

## File Structure

Source files are saved to: `{base_directory}/agent_io/source/{relative_path}.json`

Format: JSON array of items with source_guid deduplication

## Benefits

1. **Single Implementation** - One source saving implementation for both modes
2. **Consistent Format** - Both modes use array format with deduplication
3. **Configurable Locking** - Enable/disable based on concurrency needs
4. **Thread-Safe** - File locking prevents corruption in parallel scenarios

## Related Components

- **BatchService**: Uses this saver for batch task source saving
- **StagingLoader**: May use this for staging source data
- **ExtractorsSourceDataLoader**: Uses this for online source saving
- **SourcePathManager**: Path resolution for source files

## See Also

- Architecture docs: `dev_artefacts/BATCH_REALTIME_ARCHITECTURE.md`
- Tests: `tests/utilities/test_unified_source_data_saver.py`
- Plan: Phase 4 in consolidation plan
"""

import json
import logging
from enum import Enum
from typing import List, Dict, Union, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Conditional import for file locking (optional dependency)
try:
    import portalocker
    PORTALOCKER_AVAILABLE = True
except ImportError:
    PORTALOCKER_AVAILABLE = False
    logger.warning(
        "portalocker not available - file locking disabled. "
        "Install portalocker for thread-safe batch processing: pip install portalocker"
    )


class SourceSaveMode(Enum):
    """Source data save modes."""
    BATCH = "batch"    # Array format, file locking, deduplication
    ONLINE = "online"  # Optional locking/dedup for future parallel processing


class UnifiedSourceDataSaver:
    """
    Unified source data saver with configurable deduplication and locking.

    This saver provides a consistent interface for saving source data across
    batch and online modes while allowing mode-specific optimizations.
    """

    def __init__(
        self,
        base_directory: str,
        enable_deduplication: bool = True,
        enable_locking: bool = True
    ):
        """
        Initialize unified source data saver.

        Args:
            base_directory: Base directory for workflow (e.g., '/path/to/workflow')
            enable_deduplication: Whether to deduplicate by source_guid (default: True)
            enable_locking: Whether to use file locking for thread safety (default: True)

        Note:
            If portalocker is not installed and enable_locking=True, locking will be
            automatically disabled with a warning.
        """
        self.base_directory = Path(base_directory)
        self.enable_deduplication = enable_deduplication
        self.enable_locking = enable_locking and PORTALOCKER_AVAILABLE

        if enable_locking and not PORTALOCKER_AVAILABLE:
            logger.warning(
                "File locking requested but portalocker not available - "
                "locking disabled. Install: pip install portalocker"
            )

    def save_source_items(
        self,
        items: Union[Dict, List[Dict]],
        relative_path: str
    ) -> None:
        """
        Save source data with optional deduplication and locking.

        This method handles the complete source saving workflow:
        1. Normalize items to list
        2. Build source file path
        3. Load existing items (if file exists)
        4. Deduplicate by source_guid (if enabled)
        5. Merge and save

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

        # Build source file path
        source_dir = self.base_directory / 'agent_io' / 'source'
        source_dir.mkdir(parents=True, exist_ok=True)
        source_file = source_dir / f'{relative_path}.json'

        # Ensure parent directories exist
        source_file.parent.mkdir(parents=True, exist_ok=True)

        logger.debug(
            f"Saving {len(items)} source items to {source_file} "
            f"(dedup={self.enable_deduplication}, lock={self.enable_locking})"
        )

        # Save with or without locking
        if self.enable_locking:
            self._save_with_lock(source_file, items)
        else:
            self._save_without_lock(source_file, items)

        logger.info(f"Saved {len(items)} source items to {source_file}")

    def _save_with_lock(self, source_file: Path, new_items: List[Dict]) -> None:
        """
        Save with exclusive file lock (batch mode pattern).

        Uses portalocker to ensure thread-safe writes when multiple processes
        may be writing to the same file.

        Args:
            source_file: Path to source file
            new_items: List of new items to append

        Raises:
            IOError: If file locking fails or write fails
        """
        if not PORTALOCKER_AVAILABLE:
            logger.warning("Locking requested but portalocker unavailable - using unlocked save")
            return self._save_without_lock(source_file, new_items)

        try:
            with portalocker.Lock(source_file, 'a+', timeout=10) as fh:
                # Read existing items
                fh.seek(0)
                content = fh.read()
                try:
                    existing = json.loads(content) if content else []
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in {source_file}, starting fresh")
                    existing = []

                # Merge with deduplication if enabled
                if self.enable_deduplication:
                    deduplicated = self._deduplicate_by_source_guid(existing, new_items)
                    existing.extend(deduplicated)
                else:
                    existing.extend(new_items)

                # Write back
                fh.seek(0)
                fh.truncate()
                json.dump(existing, fh, indent=2, ensure_ascii=False)

        except portalocker.exceptions.LockException as e:
            logger.error(f"Failed to acquire lock on {source_file}: {e}")
            raise IOError(f"Failed to acquire file lock: {e}") from e

    def _save_without_lock(self, source_file: Path, new_items: List[Dict]) -> None:
        """
        Save without locking (online mode pattern).

        Simpler implementation for single-threaded scenarios where file locking
        is not required.

        Args:
            source_file: Path to source file
            new_items: List of new items to append

        Raises:
            IOError: If file read/write fails
        """
        existing = []

        # Read existing items if file exists
        if source_file.exists():
            try:
                with open(source_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    existing = json.loads(content) if content else []
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in {source_file}, starting fresh")
                existing = []

        # Merge with deduplication if enabled
        if self.enable_deduplication:
            deduplicated = self._deduplicate_by_source_guid(existing, new_items)
            existing.extend(deduplicated)
        else:
            existing.extend(new_items)

        # Write back
        with open(source_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

    def _deduplicate_by_source_guid(
        self,
        existing_items: List[Dict],
        new_items: List[Dict]
    ) -> List[Dict]:
        """
        Deduplicate new items by source_guid.

        Only includes new items whose source_guid is not already present
        in existing items.

        Args:
            existing_items: Existing items in the file
            new_items: New items to potentially add

        Returns:
            List of new items that don't have duplicate source_guids

        Example:
            >>> existing = [{'source_guid': 'guid1', 'data': 'old'}]
            >>> new = [
            ...     {'source_guid': 'guid1', 'data': 'new'},  # Duplicate
            ...     {'source_guid': 'guid2', 'data': 'new'}   # Unique
            ... ]
            >>> saver._deduplicate_by_source_guid(existing, new)
            [{'source_guid': 'guid2', 'data': 'new'}]
        """
        # Build set of existing source_guids
        existing_guids = {
            item.get('source_guid')
            for item in existing_items
            if item.get('source_guid')
        }

        # Filter new items
        deduplicated = [
            item for item in new_items
            if item.get('source_guid') and item.get('source_guid') not in existing_guids
        ]

        if len(deduplicated) < len(new_items):
            duplicates_count = len(new_items) - len(deduplicated)
            logger.debug(
                f"Deduplicated {duplicates_count} items with duplicate source_guids "
                f"({len(deduplicated)} unique items remaining)"
            )

        return deduplicated


# Convenience function for getting saver instance
def get_source_data_saver(
    base_directory: str,
    mode: SourceSaveMode = SourceSaveMode.BATCH
) -> UnifiedSourceDataSaver:
    """
    Get UnifiedSourceDataSaver instance with mode-specific defaults.

    Args:
        base_directory: Base directory for workflow
        mode: Save mode (BATCH or ONLINE)

    Returns:
        UnifiedSourceDataSaver configured for the specified mode

    Example:
        >>> # Batch mode (locking + deduplication)
        >>> saver = get_source_data_saver('/workflow', SourceSaveMode.BATCH)

        >>> # Online mode (no locking)
        >>> saver = get_source_data_saver('/workflow', SourceSaveMode.ONLINE)
    """
    if mode == SourceSaveMode.BATCH:
        return UnifiedSourceDataSaver(
            base_directory=base_directory,
            enable_deduplication=True,
            enable_locking=True
        )
    else:  # ONLINE
        return UnifiedSourceDataSaver(
            base_directory=base_directory,
            enable_deduplication=True,
            enable_locking=False  # Online is single-threaded
        )
