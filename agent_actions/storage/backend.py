"""Abstract storage backend interface for extensible data persistence."""

from abc import ABC, abstractmethod
from enum import Enum
from types import TracebackType
from typing import Any

from agent_actions.config.defaults import StorageDefaults
from agent_actions.record.lifecycle_read import reset_for_downstream, validate_lifecycle_batch

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
    """Abstract interface for pluggable storage backends (SQLite, S3, DuckDB, etc.)."""

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

    @abstractmethod
    def write_target(self, action_name: str, relative_path: str, data: list[dict[str, Any]]) -> str:
        """Write target data for a specific node."""
        ...

    def read_target(self, action_name: str, relative_path: str) -> list[dict[str, Any]]:
        """Read target data, validate lifecycle fields, and reset for downstream.

        Subclasses implement _read_target_raw(). This method adds lifecycle
        validation and executor boundary reset so every backend gets them
        automatically.

        Raises:
            FileNotFoundError: If the target data doesn't exist.
        """
        result = self._read_target_raw(action_name, relative_path)
        validate_lifecycle_batch(result, action_name=action_name)
        reset_for_downstream(result, action_name=action_name)
        return result

    @abstractmethod
    def _read_target_raw(self, action_name: str, relative_path: str) -> list[dict[str, Any]]:
        """Read raw target data from storage. Subclasses implement this."""
        ...

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
        pass

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
