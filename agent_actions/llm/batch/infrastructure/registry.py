"""Thread-safe batch registry with in-memory caching, backed by StorageBackend."""

import dataclasses
import json
import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry, BatchRegistryStats
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.cache_events import (
    CacheHitEvent,
    CacheLoadEvent,
    CacheMissEvent,
    CacheUpdateEvent,
)

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class BatchRegistryManager:
    """Thread-safe CRUD for batch registry with in-memory caching.

    Persists to StorageBackend metadata store under key
    ``{METADATA_KEY_PREFIX}{action_name}``.
    """

    METADATA_KEY_PREFIX = "batch_registry:"

    def __init__(self, storage_backend: "StorageBackend", action_name: str):
        self._backend = storage_backend
        self._action_name = action_name
        self._metadata_key = f"{self.METADATA_KEY_PREFIX}{action_name}"
        self._cache: dict[str, BatchJobEntry] | None = None
        self._batch_id_index: dict[str, str] | None = None
        self._lock = threading.Lock()
        logger.debug("Initialized BatchRegistryManager for action %s", action_name)

    @classmethod
    def list_action_names(cls, storage_backend: "StorageBackend") -> list[str]:
        """Return the action names that have a batch registry in the given backend."""
        keys = storage_backend.list_metadata_prefix(cls.METADATA_KEY_PREFIX)
        return [k.removeprefix(cls.METADATA_KEY_PREFIX) for k in keys]

    # ============================================================
    # PUBLIC API - Thread-safe operations
    # ============================================================

    def save_batch_job(self, file_name: str, entry: BatchJobEntry) -> None:
        with self._lock:
            cache = self._get_cache()
            old = cache.get(file_name)
            if old and self._batch_id_index is not None and old.batch_id != entry.batch_id:
                self._batch_id_index.pop(old.batch_id, None)
            cache[file_name] = entry
            if self._batch_id_index is not None:
                self._batch_id_index[entry.batch_id] = file_name
            self._persist_registry(cache)
            logger.info("Saved batch job %s for file %s", entry.batch_id, file_name)
            fire_event(CacheUpdateEvent(cache_type="batch_registry", key=file_name))

    def remove_batch_job(self, file_name: str) -> bool:
        with self._lock:
            cache = self._get_cache()
            if file_name not in cache:
                return False
            old_entry = cache[file_name]
            if self._batch_id_index is not None and old_entry.batch_id in self._batch_id_index:
                del self._batch_id_index[old_entry.batch_id]
            del cache[file_name]
            self._persist_registry(cache)
            logger.info("Removed batch job entry for %s", file_name)
            return True

    def get_batch_job(self, file_name: str) -> BatchJobEntry | None:
        with self._lock:
            cache = self._get_cache()
            entry = cache.get(file_name)
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
        with self._lock:
            cache = self._get_cache()
            if self._batch_id_index is None:
                self._rebuild_batch_id_index()
            assert self._batch_id_index is not None
            file_name = self._batch_id_index.get(batch_id)
            if file_name and file_name in cache:
                fire_event(CacheHitEvent(cache_type="batch_registry", key=f"batch_id:{batch_id}"))
                return cache[file_name]
            fire_event(
                CacheMissEvent(
                    cache_type="batch_registry",
                    key=f"batch_id:{batch_id}",
                    reason="batch_id not found",
                )
            )
            return None

    def update_status(self, batch_id: str, new_status: str) -> bool:
        with self._lock:
            cache = self._get_cache()
            if self._batch_id_index is None:
                self._rebuild_batch_id_index()
            assert self._batch_id_index is not None
            file_name = self._batch_id_index.get(batch_id)
            if file_name and file_name in cache:
                updated_entry = dataclasses.replace(cache[file_name], status=new_status)
                cache[file_name] = updated_entry
                self._persist_registry(cache)
                logger.info("Updated batch %s status to %s", batch_id, new_status)
                return True
            logger.warning("Batch ID %s not found in registry", batch_id)
            return False

    def get_all_jobs(self) -> dict[str, BatchJobEntry]:
        with self._lock:
            return self._get_cache().copy()

    def get_registry_stats(self) -> BatchRegistryStats:
        with self._lock:
            cache = self._get_cache()
            stats = BatchRegistryStats(
                total_jobs=len(cache), completed=0, failed=0, in_progress=0, cancelled=0
            )
            for entry in cache.values():
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
        stats = self.get_registry_stats()
        return stats.overall_status

    def are_all_jobs_completed(self, check_provider: Callable[[str], str] | None = None) -> bool:
        with self._lock:
            cache = self._get_cache()

            if not cache:
                return True

            if check_provider:
                to_check = [
                    (file_name, entry)
                    for file_name, entry in cache.items()
                    if not entry.is_terminal
                ]
            else:
                to_check = []

            if not check_provider:
                return all(entry.is_terminal for entry in cache.values())

        updates: list[tuple[str, str]] = []
        for file_name, entry in to_check:
            try:
                actual_status = check_provider(entry.batch_id)
                if actual_status != entry.status:
                    updates.append((file_name, actual_status))
            except (OSError, ConnectionError) as e:
                logger.warning("Transient error checking status for %s: %s", entry.batch_id, e)
                return False

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
                    if not current.is_terminal:
                        self._cache[file_name] = dataclasses.replace(current, status=new_status)
                        cache_modified = True

            if cache_modified:
                self._persist_registry(self._cache)

            return all(entry.is_terminal for entry in self._cache.values())

    def has_jobs(self) -> bool:
        """Return True if the registry has any jobs."""
        with self._lock:
            return bool(self._get_cache())

    # ============================================================
    # PRIVATE METHODS
    # ============================================================

    def _rebuild_batch_id_index(self) -> None:
        self._batch_id_index = {
            entry.batch_id: file_name for file_name, entry in (self._cache or {}).items()
        }

    def _ensure_cache_loaded(self) -> None:
        if self._cache is None:
            self._cache = self._load_registry()
            self._rebuild_batch_id_index()
        if self._cache is None:
            raise RuntimeError("Cache initialization failed")

    def _get_cache(self) -> dict[str, BatchJobEntry]:
        self._ensure_cache_loaded()
        if self._cache is None:
            raise RuntimeError(
                "BatchRegistryManager._cache is None after _ensure_cache_loaded(); "
                "cache initialization failed"
            )
        return self._cache

    def _load_registry(self) -> dict[str, BatchJobEntry]:
        raw = self._backend.load_metadata(self._metadata_key)
        if raw is None:
            fire_event(
                CacheLoadEvent(
                    cache_type="batch_registry", entries_loaded=0, source="backend (not found)"
                )
            )
            return {}

        try:
            raw_data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("Corrupted registry metadata for %s: %s", self._action_name, e)
            fire_event(
                CacheLoadEvent(
                    cache_type="batch_registry", entries_loaded=0, source="backend (corrupted)"
                )
            )
            return {}

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
                cache_type="batch_registry", entries_loaded=len(registry), source="backend"
            )
        )
        return registry

    def _persist_registry(self, registry: dict[str, BatchJobEntry]) -> None:
        raw_data = {file_name: entry.to_dict() for file_name, entry in registry.items()}
        self._backend.save_metadata(self._metadata_key, json.dumps(raw_data, ensure_ascii=False))
        logger.debug(
            "Registry persisted for action %s (%d entries)", self._action_name, len(registry)
        )
