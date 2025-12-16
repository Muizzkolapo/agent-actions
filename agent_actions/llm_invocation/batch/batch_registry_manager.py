"""
Batch Registry Manager.

Centralized management of .batch_registry.json with caching and thread safety.
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, Optional, Callable
from agent_actions.llm_invocation.batch.batch_models import BatchJobEntry, BatchRegistryStats
from agent_actions.utilities.path_utils import ensure_directory_exists

logger = logging.getLogger(__name__)


class BatchRegistryManager:
    """
    Manages batch job registry with caching and thread-safe operations.

    Responsibilities:
    - CRUD operations on .batch_registry.json
    - In-memory caching to reduce file I/O
    - Thread-safe access with locking
    - Atomic writes to prevent corruption
    - Status aggregation and queries

    Example:
        registry_path = Path('output/batch/.batch_registry.json')
        manager = BatchRegistryManager(registry_path)

        # Save a batch job
        entry = BatchJobEntry(
            batch_id='batch_123',
            status='submitted',
            timestamp=datetime.now().isoformat(),
            provider='openai',
            record_count=100
        )
        manager.save_batch_job('file1.json', entry)

        # Retrieve it later
        retrieved = manager.get_batch_job('file1.json')
        print(retrieved.batch_id)  # 'batch_123'
    """

    def __init__(self, registry_path: Path):
        """
        Initialize registry manager.

        Args:
            registry_path: Path to .batch_registry.json file
        """
        self._registry_path = Path(registry_path)
        self._cache: Optional[Dict[str, BatchJobEntry]] = None
        self._lock = threading.Lock()
        logger.debug("Initialized BatchRegistryManager for %s", registry_path)

    # ============================================================
    # PUBLIC API - Thread-safe operations
    # ============================================================

    def save_batch_job(self, file_name: str, entry: BatchJobEntry) -> None:
        """
        Save or update a batch job entry.

        Args:
            file_name: File name key (e.g., 'input.json')
            entry: BatchJobEntry to save

        Raises:
            IOError: If write fails
        """
        with self._lock:
            self._ensure_cache_loaded()
            self._cache[file_name] = entry
            self._persist_registry(self._cache)
            logger.info("Saved batch job %s for file %s", entry.batch_id, file_name)

    def get_batch_job(self, file_name: str) -> Optional[BatchJobEntry]:
        """
        Retrieve batch job entry by file name.

        Args:
            file_name: File name key

        Returns:
            BatchJobEntry if found, None otherwise
        """
        with self._lock:
            self._ensure_cache_loaded()
            return self._cache.get(file_name)

    def get_batch_job_by_id(self, batch_id: str) -> Optional[BatchJobEntry]:
        """
        Retrieve batch job entry by batch ID.

        Args:
            batch_id: Batch job ID

        Returns:
            BatchJobEntry if found, None otherwise
        """
        with self._lock:
            self._ensure_cache_loaded()
            for entry in self._cache.values():
                if entry.batch_id == batch_id:
                    return entry
            return None

    def update_status(self, batch_id: str, new_status: str) -> bool:
        """
        Update status for a batch job.

        Args:
            batch_id: Batch job ID to update
            new_status: New status value

        Returns:
            True if updated, False if batch_id not found
        """
        with self._lock:
            self._ensure_cache_loaded()

            # Find entry by batch_id
            for file_name, entry in self._cache.items():
                if entry.batch_id == batch_id:
                    # Create updated entry (dataclasses are immutable-ish)
                    updated_entry = BatchJobEntry(
                        batch_id=entry.batch_id,
                        status=new_status,
                        timestamp=entry.timestamp,
                        provider=entry.provider,
                        record_count=entry.record_count,
                        parent_batch_id=entry.parent_batch_id,
                        retry_attempt=entry.retry_attempt,
                        retry_for_records=entry.retry_for_records,
                        has_retry_batch=entry.has_retry_batch,
                    )
                    self._cache[file_name] = updated_entry
                    self._persist_registry(self._cache)
                    logger.info("Updated batch %s status to %s", batch_id, new_status)
                    return True

            logger.warning("Batch ID %s not found in registry", batch_id)
            return False

    def get_all_jobs(self) -> Dict[str, BatchJobEntry]:
        """
        Get all batch jobs in registry.

        Returns:
            Dictionary mapping file_name -> BatchJobEntry
        """
        with self._lock:
            self._ensure_cache_loaded()
            return self._cache.copy()  # Return copy to prevent external mutation

    def get_registry_stats(self) -> BatchRegistryStats:
        """
        Get aggregated statistics for all batches.

        Returns:
            BatchRegistryStats with counts by status
        """
        with self._lock:
            self._ensure_cache_loaded()

            stats = BatchRegistryStats(
                total_jobs=len(self._cache), completed=0, failed=0, in_progress=0, cancelled=0
            )

            for entry in self._cache.values():
                if entry.status == "completed":
                    stats.completed += 1
                elif entry.status in ["failed"]:
                    stats.failed += 1
                elif entry.status in ["validating", "in_progress", "finalizing"]:
                    stats.in_progress += 1
                elif entry.status == "cancelled":
                    stats.cancelled += 1

            return stats

    def get_overall_status(self) -> str:
        """
        Get overall status across all batches.

        Returns:
            One of: 'no_batches', 'completed', 'in_progress',
                   'partial_failed', 'error'
        """
        stats = self.get_registry_stats()
        return stats.overall_status

    def are_all_jobs_completed(self, check_provider: Optional[Callable[[str], str]] = None) -> bool:
        """
        Check if all batch jobs are in terminal state.

        Args:
            check_provider: Optional callable(batch_id) -> status
                          to refresh status from provider

        Returns:
            True if all jobs completed/failed/cancelled, False otherwise
        """
        with self._lock:
            self._ensure_cache_loaded()

            if not self._cache:
                return True  # No jobs = all complete

            all_terminal = True
            cache_modified = False

            for file_name, entry in list(self._cache.items()):
                # Optionally refresh status from provider
                if check_provider and not entry.is_terminal:
                    try:
                        actual_status = check_provider(entry.batch_id)
                        if actual_status != entry.status:
                            # Update status in cache
                            updated_entry = BatchJobEntry(
                                batch_id=entry.batch_id,
                                status=actual_status,
                                timestamp=entry.timestamp,
                                provider=entry.provider,
                                record_count=entry.record_count,
                                parent_batch_id=entry.parent_batch_id,
                                retry_attempt=entry.retry_attempt,
                                retry_for_records=entry.retry_for_records,
                                has_retry_batch=entry.has_retry_batch,
                            )
                            self._cache[file_name] = updated_entry
                            cache_modified = True
                            entry = updated_entry
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        # Catch all exceptions to avoid one status check failure from breaking workflow
                        logger.warning("Failed to check status for %s: %s", entry.batch_id, e)
                        # Assume not complete on error
                        return False

                # Check terminal state
                if not entry.is_terminal:
                    all_terminal = False

            # Persist if cache was updated
            if cache_modified:
                self._persist_registry(self._cache)

            return all_terminal

    def invalidate_cache(self) -> None:
        """
        Force cache reload on next access.

        Useful for testing or when registry is modified externally.
        """
        with self._lock:
            self._cache = None
            logger.debug("Registry cache invalidated")

    # ============================================================
    # PRIVATE METHODS - Internal implementation
    # ============================================================

    def _ensure_cache_loaded(self) -> None:
        """Lazy load cache if not already loaded."""
        if self._cache is None:
            self._cache = self._load_registry()

    def _load_registry(self) -> Dict[str, BatchJobEntry]:
        """
        Load registry from disk.

        Returns:
            Dictionary of file_name -> BatchJobEntry
        """
        if not self._registry_path.exists():
            logger.debug("Registry file does not exist: %s", self._registry_path)
            return {}

        try:
            with open(self._registry_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)

            # Convert raw dict to BatchJobEntry objects
            registry = {}
            for file_name, entry_dict in raw_data.items():
                try:
                    registry[file_name] = BatchJobEntry.from_dict(entry_dict)
                except (TypeError, ValueError) as e:
                    logger.warning("Invalid entry for %s in registry: %s", file_name, e)
                    # Skip invalid entries
                    continue

            logger.debug("Loaded %d entries from registry", len(registry))
            return registry

        except json.JSONDecodeError as e:
            logger.error("Corrupted registry file %s: %s", self._registry_path, e)
            return {}
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Catch all exceptions to gracefully handle file system errors
            logger.error("Failed to load registry from %s: %s", self._registry_path, e)
            return {}

    def _persist_registry(self, registry: Dict[str, BatchJobEntry]) -> None:
        """
        Atomically write registry to disk.

        Uses atomic write pattern: write to temp file, sync, rename.
        This prevents corruption even if process crashes during write.

        Args:
            registry: Registry data to persist

        Raises:
            IOError: If write fails
        """
        # Ensure directory exists
        ensure_directory_exists(self._registry_path, is_file=True)

        # Convert BatchJobEntry objects to dicts for JSON
        raw_data = {file_name: entry.to_dict() for file_name, entry in registry.items()}

        # Atomic write pattern
        tmp_path = self._registry_path.with_suffix(".json.tmp")

        try:
            # Write to temp file
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk

            # Atomic rename (POSIX guarantees atomicity)
            tmp_path.replace(self._registry_path)

            logger.debug(
                "Registry persisted to %s (%d entries)", self._registry_path, len(registry)
            )

        except Exception as e:
            # Clean up temp file on error
            if tmp_path.exists():
                tmp_path.unlink()
            raise IOError(f"Failed to persist registry to {self._registry_path}: {e}") from e
