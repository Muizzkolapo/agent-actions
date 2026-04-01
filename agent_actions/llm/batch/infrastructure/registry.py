"""Thread-safe management of .batch_registry.json with in-memory caching."""

import dataclasses
import json
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry, BatchRegistryStats
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.cache_events import (
    CacheHitEvent,
    CacheInvalidationEvent,
    CacheLoadEvent,
    CacheMissEvent,
    CacheUpdateEvent,
)
from agent_actions.utils.path_utils import ensure_directory_exists

logger = logging.getLogger(__name__)


class BatchRegistryManager:
    """Thread-safe CRUD for .batch_registry.json with in-memory caching and atomic writes."""

    def __init__(self, registry_path: Path):
        """
        Initialize registry manager.

        Args:
            registry_path: Path to .batch_registry.json file
        """
        self._registry_path = Path(registry_path)
        self._cache: dict[str, BatchJobEntry] | None = None
        self._lock = threading.Lock()
        logger.debug("Initialized BatchRegistryManager for %s", registry_path)

    # ============================================================
    # PUBLIC API - Thread-safe operations
    # ============================================================

    def save_batch_job(self, file_name: str, entry: BatchJobEntry) -> None:
        """Save or update a batch job entry.

        Raises:
            IOError: If write fails
        """
        with self._lock:
            self._ensure_cache_loaded()
            if self._cache is None:
                raise RuntimeError(
                    "BatchRegistryManager._cache is None after _ensure_cache_loaded(); "
                    "cache initialization failed"
                )
            self._cache[file_name] = entry
            self._persist_registry(self._cache)
            logger.info("Saved batch job %s for file %s", entry.batch_id, file_name)

            fire_event(CacheUpdateEvent(cache_type="batch_registry", key=file_name))

    def remove_batch_job(self, file_name: str) -> bool:
        """Remove a batch job entry. Returns True if removed, False if not found."""
        with self._lock:
            self._ensure_cache_loaded()
            if self._cache is None:
                raise RuntimeError(
                    "BatchRegistryManager._cache is None after _ensure_cache_loaded(); "
                    "cache initialization failed"
                )
            if file_name not in self._cache:
                return False
            del self._cache[file_name]
            self._persist_registry(self._cache)
            logger.info("Removed batch job entry for %s", file_name)
            return True

    def get_batch_job(self, file_name: str) -> BatchJobEntry | None:
        """Retrieve batch job entry by file name."""
        with self._lock:
            self._ensure_cache_loaded()
            if self._cache is None:
                raise RuntimeError(
                    "BatchRegistryManager._cache is None after _ensure_cache_loaded(); "
                    "cache initialization failed"
                )
            entry = self._cache.get(file_name)

            if entry is not None:
                fire_event(CacheHitEvent(cache_type="batch_registry", key=file_name))
            else:
                fire_event(
                    CacheMissEvent(
                        cache_type="batch_registry", key=file_name, reason="file_name not in cache"
                    )
                )

            return entry

    def get_batch_job_by_id(self, batch_id: str) -> BatchJobEntry | None:
        """Retrieve batch job entry by batch ID."""
        with self._lock:
            self._ensure_cache_loaded()
            if self._cache is None:
                raise RuntimeError(
                    "BatchRegistryManager._cache is None after _ensure_cache_loaded(); "
                    "cache initialization failed"
                )
            for entry in self._cache.values():
                if entry.batch_id == batch_id:
                    fire_event(
                        CacheHitEvent(cache_type="batch_registry", key=f"batch_id:{batch_id}")
                    )
                    return entry

            fire_event(
                CacheMissEvent(
                    cache_type="batch_registry",
                    key=f"batch_id:{batch_id}",
                    reason="batch_id not found",
                )
            )
            return None

    def update_status(self, batch_id: str, new_status: str) -> bool:
        """Update status for a batch job. Returns False if batch_id not found."""
        with self._lock:
            self._ensure_cache_loaded()
            if self._cache is None:
                raise RuntimeError(
                    "BatchRegistryManager._cache is None after _ensure_cache_loaded(); "
                    "cache initialization failed"
                )

            for file_name, entry in self._cache.items():
                if entry.batch_id == batch_id:
                    updated_entry = dataclasses.replace(entry, status=new_status)
                    self._cache[file_name] = updated_entry
                    self._persist_registry(self._cache)
                    logger.info("Updated batch %s status to %s", batch_id, new_status)
                    return True

            logger.warning("Batch ID %s not found in registry", batch_id)
            return False

    def get_all_jobs(self) -> dict[str, BatchJobEntry]:
        """Get all batch jobs in registry."""
        with self._lock:
            self._ensure_cache_loaded()
            if self._cache is None:
                raise RuntimeError(
                    "BatchRegistryManager._cache is None after _ensure_cache_loaded(); "
                    "cache initialization failed"
                )
            return self._cache.copy()  # Return copy to prevent external mutation

    def get_registry_stats(self) -> BatchRegistryStats:
        """Get aggregated statistics for all batches."""
        with self._lock:
            self._ensure_cache_loaded()
            if self._cache is None:
                raise RuntimeError(
                    "BatchRegistryManager._cache is None after _ensure_cache_loaded(); "
                    "cache initialization failed"
                )

            stats = BatchRegistryStats(
                total_jobs=len(self._cache), completed=0, failed=0, in_progress=0, cancelled=0
            )

            for entry in self._cache.values():
                if entry.status == BatchStatus.COMPLETED:
                    stats.completed += 1
                elif entry.status == BatchStatus.FAILED:
                    stats.failed += 1
                elif entry.status in BatchStatus.in_flight_states():
                    stats.in_progress += 1
                elif entry.status == BatchStatus.CANCELLED:
                    stats.cancelled += 1

            return stats

    def get_overall_status(self) -> str:
        """Get overall status across all batches."""
        stats = self.get_registry_stats()
        return stats.overall_status

    def are_all_jobs_completed(self, check_provider: Callable[[str], str] | None = None) -> bool:
        """Check if all batch jobs are in terminal state.

        Args:
            check_provider: Optional callable(batch_id) -> status to refresh from provider
        """
        with self._lock:
            self._ensure_cache_loaded()
            if self._cache is None:
                raise RuntimeError(
                    "BatchRegistryManager._cache is None after _ensure_cache_loaded(); "
                    "cache initialization failed"
                )

            if not self._cache:
                return True  # No jobs = all complete

            # Collect entries that need a provider check (non-terminal) while holding the lock
            if check_provider:
                to_check = [
                    (file_name, entry)
                    for file_name, entry in self._cache.items()
                    if not entry.is_terminal
                ]
            else:
                to_check = []

            # Fast path: no provider checks needed
            if not check_provider:
                return all(entry.is_terminal for entry in self._cache.values())

        # Release the lock before performing network I/O
        updates: list[tuple[str, str]] = []  # (file_name, new_status)
        for file_name, entry in to_check:
            try:
                actual_status = check_provider(entry.batch_id)
                if actual_status != entry.status:
                    updates.append((file_name, actual_status))
            except Exception as e:
                # Avoid one status check failure from breaking workflow
                logger.warning("Failed to check status for %s: %s", entry.batch_id, e)
                return False

        # Re-acquire lock to apply updates and persist
        with self._lock:
            if self._cache is None:
                raise RuntimeError(
                    "BatchRegistryManager._cache is None after modification; "
                    "cache was unexpectedly cleared during status checks"
                )
            cache_modified = False
            for file_name, new_status in updates:
                if file_name in self._cache:
                    current = self._cache[file_name]
                    # TOCTOU guard: skip if another thread already advanced this entry to
                    # terminal between our lock release and re-acquire — keep the later write.
                    if not current.is_terminal:
                        self._cache[file_name] = dataclasses.replace(current, status=new_status)
                        cache_modified = True

            if cache_modified:
                self._persist_registry(self._cache)

            return all(entry.is_terminal for entry in self._cache.values())

    def invalidate_cache(self) -> None:
        """Force cache reload on next access."""
        with self._lock:
            entries_removed = len(self._cache) if self._cache is not None else 0
            self._cache = None
            logger.debug("Registry cache invalidated")

            fire_event(
                CacheInvalidationEvent(
                    cache_type="batch_registry",
                    entries_removed=entries_removed,
                    reason="manual invalidation",
                )
            )

    # ============================================================
    # PRIVATE METHODS - Internal implementation
    # ============================================================

    def _ensure_cache_loaded(self) -> None:
        """Lazy load cache if not already loaded."""
        if self._cache is None:
            self._cache = self._load_registry()

    def _load_registry(self) -> dict[str, BatchJobEntry]:
        """
        Load registry from disk.

        Returns:
            Dictionary of file_name -> BatchJobEntry
        """
        if not self._registry_path.exists():
            logger.debug("Registry file does not exist: %s", self._registry_path)
            fire_event(
                CacheLoadEvent(
                    cache_type="batch_registry", entries_loaded=0, source="disk (file not found)"
                )
            )
            return {}

        try:
            with open(self._registry_path, encoding="utf-8") as f:
                raw_data = json.load(f)

            registry = {}
            for file_name, entry_dict in raw_data.items():
                try:
                    registry[file_name] = BatchJobEntry.from_dict(entry_dict)
                except (TypeError, ValueError) as e:
                    logger.warning("Invalid entry for %s in registry: %s", file_name, e)
                    continue

            logger.debug("Loaded %d entries from registry", len(registry))
            fire_event(
                CacheLoadEvent(
                    cache_type="batch_registry", entries_loaded=len(registry), source="disk"
                )
            )
            return registry

        except json.JSONDecodeError as e:
            logger.error("Corrupted registry file %s: %s", self._registry_path, e)
            fire_event(
                CacheLoadEvent(
                    cache_type="batch_registry", entries_loaded=0, source="disk (corrupted file)"
                )
            )
            return {}
        except Exception as e:
            logger.error("Failed to load registry from %s: %s", self._registry_path, e)
            fire_event(
                CacheLoadEvent(cache_type="batch_registry", entries_loaded=0, source="disk (error)")
            )
            return {}

    def _persist_registry(self, registry: dict[str, BatchJobEntry]) -> None:
        """
        Atomically write registry to disk.

        Uses atomic write pattern: write to temp file, sync, rename.
        This prevents corruption even if process crashes during write.

        Args:
            registry: Registry data to persist

        Raises:
            IOError: If write fails
        """
        ensure_directory_exists(self._registry_path, is_file=True)

        raw_data = {file_name: entry.to_dict() for file_name, entry in registry.items()}

        tmp_path = self._registry_path.with_suffix(".json.tmp")

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk

            tmp_path.replace(self._registry_path)

            logger.debug(
                "Registry persisted to %s (%d entries)", self._registry_path, len(registry)
            )

        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink()
            raise OSError(f"Failed to persist registry to {self._registry_path}: {e}") from e
