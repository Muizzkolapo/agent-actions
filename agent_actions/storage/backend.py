"""Abstract storage backend interface for extensible data persistence."""

import copy
import json
import logging
from abc import ABC, abstractmethod
from enum import Enum
from types import TracebackType
from typing import Any

from agent_actions.config.defaults import StorageDefaults
from agent_actions.record.lifecycle_read import reset_for_downstream, validate_lifecycle_batch

logger = logging.getLogger(__name__)

_MAINTENANCE_RETENTION_DEFAULT = StorageDefaults.PROMPT_TRACE_RETENTION_RUNS
_MAINTENANCE_TTL_DEFAULT = StorageDefaults.SOURCE_DATA_TTL_DAYS

NODE_LEVEL_RECORD_ID = "__node__"
"""Sentinel record_id for node-level disposition signals."""
DISPOSITION_PASSTHROUGH = "passthrough"
DISPOSITION_SKIPPED = "skipped"
DISPOSITION_FILTERED = "filtered"
DISPOSITION_EXHAUSTED = "exhausted"
DISPOSITION_FAILED = "failed"
DISPOSITION_DEFERRED = "deferred"
DISPOSITION_UNPROCESSED = "unprocessed"
DISPOSITION_SUCCESS = "success"


class Disposition(str, Enum):
    """Enumeration of valid record disposition values."""

    PASSTHROUGH = DISPOSITION_PASSTHROUGH
    SKIPPED = DISPOSITION_SKIPPED
    FILTERED = DISPOSITION_FILTERED
    EXHAUSTED = DISPOSITION_EXHAUSTED
    FAILED = DISPOSITION_FAILED
    DEFERRED = DISPOSITION_DEFERRED
    UNPROCESSED = DISPOSITION_UNPROCESSED
    SUCCESS = DISPOSITION_SUCCESS


VALID_DISPOSITIONS = frozenset(d.value for d in Disposition)

# Records eligible for retry: only primary failures the user can act on.
# Excluded: success (done), unprocessed (cascade casualty — resolves when
# upstream is retried), passthrough (guard-skipped), skipped (WHERE clause),
# filtered (predicate), deferred (in-flight HITL/batch).
FAILURE_DISPOSITIONS = frozenset({DISPOSITION_FAILED, DISPOSITION_EXHAUSTED})

# Dispositions cleared when resuming an interrupted (RUNNING) action.
# Includes DEFERRED because in-flight batch/HITL items must be re-submitted.
# Excludes SUCCESS, PASSTHROUGH, FILTERED, SKIPPED so that checkpointed
# progress survives and the DispositionGate can carry it forward.
RUNNING_CLEAR_DISPOSITIONS = frozenset(
    {DISPOSITION_FAILED, DISPOSITION_EXHAUSTED, DISPOSITION_DEFERRED}
)

DispositionRow = tuple[str, str, str, str | None, str | None, str | None, str | None]
"""(action_name, record_id, disposition, reason, relative_path, input_snapshot, detail)."""


class StorageBackend(ABC):
    """Abstract interface for pluggable storage backends (SQLite, S3, DuckDB, etc.).

    Delta storage: write_target() extracts only the current action's content
    namespace before delegating to _write_target_raw(). read_target() reconstructs
    the full accumulated record from upstream deltas. This is transparent to all
    consumers — they see the exact same list[dict] as before.
    """

    _STORAGE_FORMAT_VERSION = 2  # Version 1 = full records, Version 2 = delta storage

    def __init__(self) -> None:
        """Initialize base storage backend state.

        Subclasses MUST call super().__init__() in their __init__.
        """
        self._reconstruction_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._execution_order_cache: list[str] | None = None
        self._format_version_written = False
        self._format_version_checked = False

    @classmethod
    @abstractmethod
    def create(cls, **kwargs: Any) -> "StorageBackend":
        """Factory classmethod for backend construction.

        Each backend defines its own required keyword arguments.
        """
        ...

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """Return the backend type identifier."""
        ...

    @abstractmethod
    def initialize(self) -> None:
        """Create tables, indexes, and other infrastructure required by the backend."""
        ...

    # ------------------------------------------------------------------
    # Target data: delta-aware write/read (concrete in base class)
    # ------------------------------------------------------------------

    def write_target(
        self,
        action_name: str,
        relative_path: str,
        data: list[dict[str, Any]],
        *,
        is_first_action: bool | None = None,
    ) -> str:
        """Write target data with delta extraction.

        Concrete method — subclasses do NOT override. Subclasses implement
        _write_target_raw() for the actual storage.
        """
        if is_first_action is None:
            execution_order = self._get_execution_order()
            is_first_action = bool(execution_order) and execution_order[0] == action_name

        delta_records = []
        for record in data:
            if record.get("_delta_mode") == "full":
                delta_records.append(record)
            else:
                delta_records.append(
                    self._extract_delta(record, action_name, is_first_action=is_first_action)
                )

        if not self._format_version_written:
            self.save_metadata("storage_format_version", str(self._STORAGE_FORMAT_VERSION))
            self._format_version_written = True

        self._reconstruction_cache.clear()
        return self._write_target_raw(action_name, relative_path, delta_records)

    def read_target(self, action_name: str, relative_path: str) -> list[dict[str, Any]]:
        """Read target data, reconstruct from deltas, validate lifecycle, reset for downstream.

        Concrete method — subclasses do NOT override. Subclasses implement
        _read_target_raw() for the actual storage.
        """
        if not self._format_version_checked:
            stored_version = self.load_metadata("storage_format_version")
            if stored_version is not None:
                try:
                    version_int = int(stored_version)
                except ValueError:
                    from agent_actions.errors.configuration import ConfigValidationError

                    raise ConfigValidationError(
                        f"Corrupt storage_format_version in workflow_metadata: {stored_version!r}. "
                        f"Expected an integer. Re-run with --fresh to reset.",
                        context={"stored_version": stored_version},
                    ) from None
                if version_int > self._STORAGE_FORMAT_VERSION:
                    from agent_actions.errors.configuration import ConfigValidationError

                    raise ConfigValidationError(
                        f"Database uses storage format version {version_int}, "
                        f"but this code supports up to version {self._STORAGE_FORMAT_VERSION}. "
                        f"Please upgrade agent-actions.",
                        context={
                            "stored_version": version_int,
                            "supported": self._STORAGE_FORMAT_VERSION,
                        },
                    )
            self._format_version_checked = True

        cache_key = (action_name, relative_path)
        if cache_key in self._reconstruction_cache:
            return copy.deepcopy(self._reconstruction_cache[cache_key])

        result = self._read_target_raw(action_name, relative_path)
        result = self._reconstruct_from_deltas(action_name, relative_path, result)
        validate_lifecycle_batch(result, action_name=action_name)
        reset_for_downstream(result, action_name=action_name)
        self._reconstruction_cache[cache_key] = result
        return copy.deepcopy(result)

    # ------------------------------------------------------------------
    # Abstract methods subclasses must implement
    # ------------------------------------------------------------------

    @abstractmethod
    def _write_target_raw(
        self, action_name: str, relative_path: str, data: list[dict[str, Any]]
    ) -> str:
        """Store data to the backend. Called with delta-extracted records."""
        ...

    @abstractmethod
    def _read_target_raw(self, action_name: str, relative_path: str) -> list[dict[str, Any]]:
        """Read raw target data from storage. Subclasses implement this."""
        ...

    def _read_target_raw_batch(
        self, action_names: list[str], relative_path: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch raw target data for multiple actions in one call.

        Default loops over _read_target_raw. Backends may override with
        a batched query (e.g., SQL IN clause) for efficiency.
        """
        result: dict[str, list[dict[str, Any]]] = {}
        for action in action_names:
            try:
                result[action] = self._read_target_raw(action, relative_path)
            except FileNotFoundError:
                logger.debug(
                    "Upstream action '%s' has no data for file '%s' — "
                    "will be flagged as incomplete during reconstruction.",
                    action,
                    relative_path,
                )
        return result

    @abstractmethod
    def save_metadata(self, key: str, value: str) -> None:
        """Store a metadata key-value pair (e.g., execution_order)."""
        ...

    @abstractmethod
    def load_metadata(self, key: str) -> str | None:
        """Load a metadata value by key. Returns None if not found."""
        ...

    # ------------------------------------------------------------------
    # Delta extraction and reconstruction (concrete, backend-agnostic)
    # ------------------------------------------------------------------

    def _extract_delta(
        self, record: dict[str, Any], action_name: str, *, is_first_action: bool = False
    ) -> dict[str, Any]:
        """Extract delta: preserve entire envelope, strip content to this action's namespace."""
        content = record.get("content")
        if not isinstance(content, dict):
            # No content dict — store as full (raw records, test data, etc.)
            return {**record, "_delta_mode": "full"}

        # FM9: Warn on multi-namespace records that weren't pre-tagged
        if (
            record.get("_delta_mode") != "full"
            and action_name in content
            and not is_first_action
            and len({k for k in content if k != "source"}) > 1
        ):
            logger.warning(
                "Record for '%s' has %d content namespaces but was not tagged as full. "
                "If this is a carry-forward, correlation, or expansion record, "
                "tag it with _delta_mode='full' before calling write_target. "
                "Namespaces: %s",
                action_name,
                len(content),
                sorted(content.keys()),
            )

        if action_name not in content:
            return {**record, "_delta_mode": "full"}

        if is_first_action:
            delta_content: dict[str, Any] = {}
            if "source" in content:
                delta_content["source"] = content["source"]
            delta_content[action_name] = content[action_name]
            mode = "first"
        else:
            delta_content = {action_name: content[action_name]}
            mode = "delta"

        delta = {k: v for k, v in record.items() if k != "content"}
        delta["content"] = delta_content
        delta["_delta_mode"] = mode
        return delta

    def _reconstruct_from_deltas(
        self,
        action_name: str,
        relative_path: str,
        delta_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Reconstruct full records by joining upstream deltas.

        Uses only abstract methods — no backend-specific access.
        Strips _delta_mode from ALL returned records.
        Flags records with missing upstream data as _reconstruction_incomplete.
        """
        if not delta_records or "_delta_mode" not in delta_records[0]:
            return delta_records  # Legacy DB — no reconstruction needed

        execution_order = self._get_execution_order()
        try:
            idx = execution_order.index(action_name)
        except ValueError:
            return [{k: v for k, v in r.items() if k != "_delta_mode"} for r in delta_records]
        upstream_actions = execution_order[:idx]

        if not upstream_actions:
            return [{k: v for k, v in r.items() if k != "_delta_mode"} for r in delta_records]

        # Batch fetch upstream deltas via abstract method
        upstream_data = self._read_target_raw_batch(upstream_actions, relative_path)

        # Index by (action_name, source_guid)
        upstream: dict[str, dict[str, dict[str, Any]]] = {}
        for act, records in upstream_data.items():
            guid_map: dict[str, dict[str, Any]] = {}
            for rec in records:
                guid = rec.get("source_guid")
                if guid:
                    rec_content = rec.get("content")
                    if rec_content is None:
                        logger.warning("Upstream record %s in '%s' has no content.", guid, act)
                        rec_content = {}
                    guid_map[guid] = rec_content
            upstream[act] = guid_map

        # Cross-file fallback for missing source_guids
        all_guids = {r.get("source_guid") for r in delta_records if r.get("source_guid")}
        found_guids: set[str] = set()
        for guid_map in upstream.values():
            found_guids.update(guid_map.keys())
        missing_guids = all_guids - found_guids

        if missing_guids:
            logger.warning(
                "Delta reconstruction for '%s': %d of %d source_guids not found in "
                "same-file upstream deltas. Attempting cross-file lookup.",
                action_name,
                len(missing_guids),
                len(all_guids),
            )
            still_missing = set(missing_guids)
            for act in upstream_actions:
                if not still_missing:
                    break  # All guids found
                try:
                    all_files = self.list_target_files(act)
                except FileNotFoundError:
                    logger.warning(
                        "Cross-file lookup: list_target_files('%s') failed.",
                        act,
                    )
                    continue
                for file_path in all_files:
                    if file_path == relative_path:
                        continue
                    try:
                        file_records = self._read_target_raw(act, file_path)
                    except FileNotFoundError:
                        continue
                    for rec in file_records:
                        guid = rec.get("source_guid")
                        if guid and guid in still_missing:
                            rec_content = rec.get("content")
                            if rec_content is None:
                                rec_content = {}
                            upstream.setdefault(act, {})[guid] = rec_content
                            still_missing.discard(guid)

        # Merge and strip _delta_mode
        reconstructed: list[dict[str, Any]] = []
        for record in delta_records:
            mode = record.get("_delta_mode")
            if mode in ("first", "full") or mode is None:
                clean = {k: v for k, v in record.items() if k != "_delta_mode"}
                reconstructed.append(clean)
                continue

            guid = record.get("source_guid")
            full_content: dict[str, Any] = {}
            missing_upstream: list[str] = []
            for act in upstream_actions:
                act_deltas = upstream.get(act, {})
                delta_content = act_deltas.get(guid) if guid else None
                if delta_content is None:
                    missing_upstream.append(act)
                else:
                    full_content.update(delta_content)

            current_content = record.get("content")
            if current_content is not None:
                full_content.update(current_content)
            else:
                logger.error("Delta record %s in '%s' has no content key.", guid, action_name)

            full_record = {k: v for k, v in record.items() if k != "content" and k != "_delta_mode"}
            full_record["content"] = full_content

            if missing_upstream:
                logger.warning(
                    "Record %s in '%s' missing upstream deltas from: %s. "
                    "Content may be incomplete.",
                    guid,
                    action_name,
                    missing_upstream,
                )
                full_record["_reconstruction_incomplete"] = True

            reconstructed.append(full_record)

        return reconstructed

    def _get_execution_order(self) -> list[str]:
        """Get the workflow execution order from metadata. Cached per instance."""
        if self._execution_order_cache is not None:
            return self._execution_order_cache
        raw = self.load_metadata("execution_order")
        if raw is None:
            logger.debug("No execution_order in workflow_metadata — delta reconstruction disabled.")
            return []
        self._execution_order_cache = json.loads(raw)
        return self._execution_order_cache

    @abstractmethod
    def write_source(
        self,
        relative_path: str,
        data: list[dict[str, Any]],
        enable_deduplication: bool = True,
    ) -> str:
        """Write source data with optional deduplication by source_guid."""
        ...

    @abstractmethod
    def read_source(self, relative_path: str) -> list[dict[str, Any]]:
        """Read source data.

        Raises:
            FileNotFoundError: If the source data doesn't exist.
        """
        ...

    @abstractmethod
    def list_target_files(self, action_name: str) -> list[str]:
        """List all target file paths for a specific node."""
        ...

    @abstractmethod
    def list_source_files(self) -> list[str]:
        """List all source file paths."""
        ...

    @abstractmethod
    def preview_target(
        self,
        action_name: str,
        limit: int = 10,
        offset: int = 0,
        relative_path: str | None = None,
    ) -> dict[str, Any]:
        """Preview target data for a node with pagination."""
        ...

    @abstractmethod
    def get_storage_stats(self) -> dict[str, Any]:
        """Get storage statistics (record counts, DB size, per-node breakdown)."""
        ...

    def set_disposition(  # noqa: B027
        self,
        action_name: str,
        record_id: str,
        disposition: str | Disposition,
        reason: str | None = None,
        relative_path: str | None = None,
        input_snapshot: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Write a disposition record (use NODE_LEVEL_RECORD_ID for node-level signals).

        Args:
            input_snapshot: JSON-serialized input record for failed items.
                Implementations SHOULD truncate to a reasonable limit (recommended 10KB).
            detail: Extended error message or context for the disposition.
        """
        # No-op: subclass must override to persist dispositions.

    def set_dispositions_batch(
        self,
        dispositions: list[DispositionRow],
    ) -> None:
        """Write multiple disposition records in a single transaction.

        Default implementation loops over set_disposition. Backends may
        override for batch-optimized writes.
        """
        for action_name, record_id, disposition, reason, rp, snapshot, detail in dispositions:
            self.set_disposition(
                action_name,
                record_id,
                disposition,
                reason=reason,
                relative_path=rp,
                input_snapshot=snapshot,
                detail=detail,
            )

    def get_disposition(
        self,
        action_name: str,
        record_id: str | None = None,
        disposition: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query disposition records with optional filters."""
        return []

    def has_disposition(
        self,
        action_name: str,
        disposition: str,
        record_id: str | None = None,
    ) -> bool:
        """Check whether at least one matching disposition exists."""
        return False

    def get_terminal_record_ids(self, action_name: str) -> set[str]:
        """Return record_ids with any gate-terminal disposition for an action."""
        return set()

    def clear_disposition(
        self,
        action_name: str,
        disposition: str | None = None,
        record_id: str | None = None,
    ) -> int:
        """Delete matching disposition records. Returns count deleted."""
        return 0

    def save_checkpoint_records(  # noqa: B027
        self,
        action_name: str,
        relative_path: str,
        records: list[dict[str, Any]],
    ) -> None:
        """Upsert records into the checkpoint output table.

        Used for incremental checkpointing during online processing.
        Uses INSERT OR REPLACE keyed on (action_name, relative_path, source_guid).
        """

    def read_checkpoint_records(
        self,
        action_name: str,
        relative_path: str,
    ) -> list[dict[str, Any]]:
        """Read all checkpointed records for an action/path."""
        return []

    def clear_checkpoint_records(  # noqa: B027
        self,
        action_name: str,
        relative_path: str | None = None,
    ) -> None:
        """Delete checkpoint records for an action after successful completion.

        If relative_path is provided, only records for that path are cleared.
        Otherwise all checkpoint records for the action are removed.
        """

    def get_failed_items(self, action_name: str) -> list[dict[str, Any]]:
        """Return item-level failure dispositions, excluding node-level sentinels."""
        return [
            d
            for d in self.get_disposition(action_name, disposition=DISPOSITION_FAILED)
            if d.get("record_id") != NODE_LEVEL_RECORD_ID
        ]

    def has_successful_items(self, action_name: str) -> bool:
        """Return True if at least one item-level success disposition exists."""
        return any(
            d.get("record_id") != NODE_LEVEL_RECORD_ID
            for d in self.get_disposition(action_name, disposition=DISPOSITION_SUCCESS)
        )

    # ------------------------------------------------------------------
    # Prompt trace methods (compilation-level observability)
    # ------------------------------------------------------------------

    def write_prompt_trace(  # noqa: B027
        self,
        action_name: str,
        record_id: str,
        compiled_prompt: str,
        llm_context: str | None = None,
        response_text: str | None = None,
        model_name: str | None = None,
        model_vendor: str | None = None,
        run_mode: str | None = None,
        attempt: int = 0,
    ) -> None:
        """Persist the compiled prompt and LLM context for a single record.

        This is telemetry. Implementations should not raise on failure.
        """

    def update_prompt_trace_response(  # noqa: B027
        self,
        action_name: str,
        record_id: str,
        response_text: str,
        attempt: int = 0,
    ) -> None:
        """Update an existing trace with the LLM response.

        No-op if the trace does not exist. This is telemetry — must not raise.
        """

    def get_prompt_traces(
        self,
        action_name: str,
        record_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve prompt traces for an action, optionally filtered by record."""
        return []

    def get_prompt_trace_summary(
        self,
        action_name: str,
    ) -> dict[str, Any] | None:
        """Return a representative trace for an action with aggregate stats."""
        return None

    def preview_prompt_traces(
        self,
        action_name: str,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Paginated access to per-record traces."""
        return {"records": [], "total_count": 0, "action_name": action_name}

    def clear_prompt_traces(
        self,
        action_name: str | None = None,
    ) -> int:
        """Delete traces for an action, or all if action_name is None."""
        return 0

    def clear_source_data(self) -> None:
        """Delete all rows from the source_data table."""
        raise NotImplementedError(f"{type(self).__name__} must implement clear_source_data()")

    def delete_target(self, action_name: str) -> int:
        """Delete all target data for an action. Returns count deleted.

        Subclasses **must** override — the default raises so that backend
        authors are forced to implement it and ``--fresh`` cannot silently
        leave stale data behind.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement delete_target()")

    def perform_maintenance(  # noqa: B027
        self,
        prompt_trace_retention_runs: int = _MAINTENANCE_RETENTION_DEFAULT,
        source_data_ttl_days: int | None = _MAINTENANCE_TTL_DEFAULT,
    ) -> None:
        """Run post-workflow maintenance (WAL checkpoint, cleanup stale data).

        Default is no-op. SQLiteBackend overrides with actual maintenance.
        """
        pass

    def close(self) -> None:  # noqa: B027
        """Close the storage backend and release resources."""
        self._reconstruction_cache.clear()
        self._execution_order_cache = None

    def __enter__(self) -> "StorageBackend":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit - ensures cleanup."""
        self.close()
