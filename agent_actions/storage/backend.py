"""Abstract storage backend interface for extensible data persistence."""

import copy
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Any

from agent_actions.config.defaults import StorageDefaults
from agent_actions.logging.diagnostics import DIAGNOSTIC
from agent_actions.record.lifecycle_read import reset_for_downstream, validate_lifecycle_batch
from agent_actions.record.reasons import PARSE_ERROR
from agent_actions.utils.schema_echo import is_schema_echo, make_schema_echo_error

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

TERMINAL_DISPOSITIONS = frozenset(
    {
        DISPOSITION_SUCCESS,
        DISPOSITION_FILTERED,
        DISPOSITION_SKIPPED,
        DISPOSITION_PASSTHROUGH,
        DISPOSITION_EXHAUSTED,
    }
)

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
        """Initialize base storage backend state."""
        self._reconstruction_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._execution_order_cache: list[str] | None = None
        self._dependency_graph_cache: dict[str, list[str]] | None = None
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

    def _gate_schema_echo_records(
        self,
        action_name: str,
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Replace a schema-echo namespace with a parse-error sentinel before persistence.

        Guards the persistence seams that never re-invoke the LLM — ``write_target`` and
        ``save_checkpoint_records`` — both of which persist content-nested records, so the
        check reads ``record["content"][action_name]``. The record keeps flowing (namespace
        swapped for ``make_schema_echo_error``, FAILED/PARSE_ERROR disposition) so the
        failure stays queryable rather than being silently dropped.
        """
        gated: list[dict[str, Any]] = []
        failed_rows: list[DispositionRow] = []
        for record in records:
            content = record.get("content")
            if not isinstance(content, dict) or action_name not in content:
                gated.append(record)
                continue
            ns_value = content[action_name]
            if not is_schema_echo(ns_value):
                gated.append(record)
                continue

            source_guid = record.get("source_guid")
            logger.warning(
                "[%s] Schema-echo in delta for source_guid=%s (keys: %s) — "
                "replacing with parse-error sentinel",
                action_name,
                source_guid,
                sorted(ns_value.keys()),
            )
            gated.append(
                {**record, "content": {**content, action_name: make_schema_echo_error(ns_value)}}
            )

            if source_guid:
                failed_rows.append(
                    (action_name, source_guid, DISPOSITION_FAILED, PARSE_ERROR, None, None, None)
                )

        if failed_rows:
            try:
                self.set_dispositions_batch(failed_rows)
            except NotImplementedError:
                logger.warning(
                    "[%s] Disposition write skipped for %d record(s) — "
                    "backend has no set_dispositions_batch",
                    action_name,
                    len(failed_rows),
                    extra=DIAGNOSTIC,
                )
        return gated

    def write_target(
        self,
        action_name: str,
        relative_path: str,
        data: list[dict[str, Any]],
        *,
        is_first_action: bool | None = None,
        force_full: bool = False,
    ) -> str:
        """Write target data with delta extraction."""
        if force_full:
            delta_records = [{**r, "_delta_mode": "full"} for r in data]
        else:
            if is_first_action is None:
                execution_order = self._get_execution_order()
                is_first_action = bool(execution_order) and execution_order[0] == action_name

            # Read once for the batch, and only if some row might be stored as a
            # delta: a write whose every row is already marked whole — an
            # expansion, a FILE tool's invented rows — pays nothing for the check.
            upstream_guids: set[str] | None = None
            delta_records = []
            for record in data:
                if record.get("_delta_mode") == "full":
                    delta_records.append(record)
                else:
                    if upstream_guids is None:
                        upstream_guids = self._joinable_identities(action_name, relative_path)
                    delta_records.append(
                        self._extract_delta(
                            record,
                            action_name,
                            is_first_action=is_first_action,
                            upstream_guids=upstream_guids,
                        )
                    )

        # Refuse to persist namespaces that are the compiled JSON Schema instead of
        # LLM output — the carry-forward / resume path bypasses the live-LLM guard.
        delta_records = self._gate_schema_echo_records(action_name, delta_records)

        if not self._format_version_written:
            self.save_metadata("storage_format_version", str(self._STORAGE_FORMAT_VERSION))
            self._format_version_written = True

        self._reconstruction_cache.clear()
        return self._write_target_raw(action_name, relative_path, delta_records)

    def read_target(self, action_name: str, relative_path: str) -> list[dict[str, Any]]:
        """Read target data, reconstruct from deltas, validate lifecycle, reset for downstream.

        Raises:
            FileNotFoundError: If the target data doesn't exist.
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

        result = self._reconstructed_target(action_name, relative_path)
        reset_for_downstream(result, action_name=action_name)
        return result

    def read_target_for_rewrite(self, action_name: str, relative_path: str) -> list[dict[str, Any]]:
        """Reconstructed rows of an action's own output, without the downstream reset.

        For a caller writing these rows back where they came from — carry-forward
        rebuilds the whole file, so a record it does not reprocess still has to be
        handed back to the write. :meth:`read_target` would hand it back as ACTIVE,
        which is the truth for a consumer reading forward and a lie about an action
        whose output for that record already exists.

        Rows stored whole are handed back marked so: re-deriving the mode cannot
        see a producer's own stamp on a row whose identity its upstream holds, and
        would rewrite that row as a delta.

        Raises:
            FileNotFoundError: If the target data doesn't exist.
        """
        rows = self._reconstructed_target(action_name, relative_path)
        stored = self._read_target_raw(action_name, relative_path)
        # Positional, not keyed on the guid: reconstruction is one row out per row
        # in and keeps their order, while several rows can share one identity — a
        # guid set would mark a delta row stored beside a whole one.
        if len(stored) != len(rows):
            # Reconstruction is one row out per row in, so this cannot happen; say
            # so rather than skip quietly, because skipping changes how a row is
            # stored on the way back in.
            logger.warning(
                "Action '%s': %d stored row(s) reconstructed to %d for %s, so how each "
                "was stored cannot be carried into a rewrite; a row stored whole under "
                "an identity its upstream holds will be rewritten as a delta",
                action_name,
                len(stored),
                len(rows),
                relative_path,
            )
            return rows
        for row, raw in zip(rows, stored, strict=True):
            if raw.get("_delta_mode") == "full":
                row["_delta_mode"] = "full"
        return rows

    def _reconstructed_target(self, action_name: str, relative_path: str) -> list[dict[str, Any]]:
        """Stored rows, reconstructed and lifecycle-validated. Cached pre-reset."""
        cache_key = (action_name, relative_path)
        if cache_key not in self._reconstruction_cache:
            result = self._read_target_raw(action_name, relative_path)
            result = self._reconstruct_from_deltas(action_name, relative_path, result)
            validate_lifecycle_batch(result, action_name=action_name)
            self._reconstruction_cache[cache_key] = result
        return copy.deepcopy(self._reconstruction_cache[cache_key])

    def target_rows_per_source_guid(self, action_name: str) -> dict[str, int]:
        """How many stored rows this action holds for each identity.

        A count, not a set: source_guid is a content hash, so byte-identical
        records share one and an action can hold several rows under it. A caller
        deciding which rows must survive needs to know how many stood there —
        a set would let it write three where one did, or keep one where three did.

        Reads the rows as stored. Reconstruction from deltas, lifecycle
        validation and the downstream reset that :meth:`read_target` performs
        are all irrelevant to an identity, and expensive enough to matter to a
        caller asking this per input file — one of them also raises on a store
        that a plain read would only have complained about later.
        """
        counts: dict[str, int] = {}
        for relative_path in self.list_target_files(action_name):
            try:
                rows = self._read_target_raw(action_name, relative_path)
            except FileNotFoundError:
                logger.debug(
                    "Target file listed but unreadable while counting rows: %s/%s",
                    action_name,
                    relative_path,
                )
                continue
            for row in rows:
                if isinstance(row, dict):
                    guid = row.get("source_guid")
                    if guid:
                        counts[guid] = counts.get(guid, 0) + 1
        return counts

    @abstractmethod
    def _write_target_raw(
        self, action_name: str, relative_path: str, data: list[dict[str, Any]]
    ) -> str:
        """Store delta-extracted records to the backend."""
        ...

    @abstractmethod
    def _read_target_raw(self, action_name: str, relative_path: str) -> list[dict[str, Any]]:
        """Read raw target data from storage."""
        ...

    def _read_target_raw_batch(
        self, action_names: list[str], relative_path: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch target data for multiple actions. Override for batched queries."""
        result: dict[str, list[dict[str, Any]]] = {}
        for action in action_names:
            try:
                result[action] = self._read_target_raw(action, relative_path)
            except FileNotFoundError:
                pass
        return result

    def save_metadata(self, key: str, value: str) -> None:
        """Store a metadata key-value pair. Clears related caches."""
        self._save_metadata_raw(key, value)
        if key == "execution_order":
            self._execution_order_cache = None
        elif key == "dependency_graph":
            self._dependency_graph_cache = None

    @abstractmethod
    def _save_metadata_raw(self, key: str, value: str) -> None:
        """Store a metadata key-value pair to the backend."""
        ...

    @abstractmethod
    def load_metadata(self, key: str) -> str | None:
        """Load a metadata value by key. Returns None if not found."""
        ...

    def delete_metadata(self, key: str) -> bool:
        """Delete a metadata key. Returns True if deleted."""
        raise NotImplementedError(f"{type(self).__name__} must implement delete_metadata()")

    def delete_metadata_prefix(self, prefix: str) -> int:
        """Delete all metadata keys starting with prefix. Returns count deleted."""
        raise NotImplementedError(f"{type(self).__name__} must implement delete_metadata_prefix()")

    def list_metadata_prefix(self, prefix: str) -> list[str]:
        """Return all metadata keys starting with `prefix`, sorted lexically."""
        raise NotImplementedError(f"{type(self).__name__} must implement list_metadata_prefix()")

    def _joinable_identities(self, action_name: str, relative_path: str) -> set[str]:
        """Identities the upstream actions hold for this file.

        Measures at write time what :meth:`_reconstruct_from_deltas` will try to
        rejoin at read time, over the same actions and the same file. An action
        with no upstream returns the empty set, which is the same answer as an
        upstream holding nothing: either way a delta would rejoin nothing.

        A missing upstream file counts as holding nothing rather than raising —
        it is what reconstruction will find too.
        """
        upstream_actions = self._get_upstream_actions(action_name)
        if not upstream_actions:
            return set()

        identities: set[str] = set()
        for records in self._read_target_raw_batch(upstream_actions, relative_path).values():
            for record in records:
                if isinstance(record, dict):
                    guid = record.get("source_guid")
                    content = record.get("content")
                    # Content, not just the identity: a row stored without usable
                    # content is rejoined as nothing, so counting its identity
                    # would call a row joinable that rejoins an empty namespace.
                    if guid and isinstance(content, dict) and content:
                        identities.add(guid)
        return identities

    def _extract_delta(
        self,
        record: dict[str, Any],
        action_name: str,
        *,
        is_first_action: bool = False,
        upstream_guids: set[str],
    ) -> dict[str, Any]:
        """Extract delta: preserve entire envelope, strip content to this action's namespace.

        ``upstream_guids`` is required because whether a row is storable as a
        delta is not a property of the row: storing one discards every namespace
        above this action, and only the identities upstream holds say whether
        reconstruction could put them back.
        """
        content = record.get("content")
        if not isinstance(content, dict):
            return {**record, "_delta_mode": "full"}

        if not record.get("source_guid"):
            return {**record, "_delta_mode": "full"}

        if action_name not in content:
            return {**record, "_delta_mode": "full"}

        if is_first_action:
            delta_content: dict[str, Any] = {}
            if "source" in content:
                delta_content["source"] = content["source"]
            delta_content[action_name] = content[action_name]
            mode = "first"
        elif record["source_guid"] not in upstream_guids:
            # Dropping the other namespaces promises they can be rejoined under
            # this identity, and nothing upstream holds it to rejoin them from.
            return {**record, "_delta_mode": "full"}
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
        """Reconstruct full records by joining upstream deltas."""
        # records[0] answers for the batch only about the key's presence: every
        # record gets one from write_target. The values differ — a minted row is
        # stored whole beside deltas — so the loop reads each record's own mode.
        if not delta_records or "_delta_mode" not in delta_records[0]:
            return delta_records

        upstream_actions = self._get_upstream_actions(action_name)

        if not upstream_actions:
            return [{k: v for k, v in r.items() if k != "_delta_mode"} for r in delta_records]

        upstream_data = self._read_target_raw_batch(upstream_actions, relative_path)

        # Index upstream deltas by (action_name, source_guid).
        # Track which guids have a "full" record — those are self-contained
        # and we don't need to look further upstream for that guid.
        upstream: dict[str, dict[str, dict[str, Any]]] = {}
        full_boundary_guids: dict[str, str] = {}  # guid → action that has full record
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
                    if rec.get("_delta_mode") == "full":
                        full_boundary_guids[guid] = act
            upstream[act] = guid_map

        # For each current record, determine how far back to reconstruct.
        # If a "full" upstream record exists for this guid, only merge from
        # that point forward — the full record already contains everything
        # before it (expansion records embed upstream content).
        reconstructed: list[dict[str, Any]] = []
        for record in delta_records:
            mode = record.get("_delta_mode")
            if mode in ("first", "full") or mode is None:
                clean = {k: v for k, v in record.items() if k != "_delta_mode"}
                reconstructed.append(clean)
                continue

            guid = record.get("source_guid")

            # A whole row carries everything above the action that stored it, so
            # its ancestors are superseded. Its peers are not above it and hold
            # namespaces it never carried, so they still merge.
            boundary_action = full_boundary_guids.get(guid) if guid else None
            if boundary_action and boundary_action in upstream_actions:
                superseded = set(self._get_upstream_actions(boundary_action))
                merge_actions = [a for a in upstream_actions if a not in superseded]
            else:
                merge_actions = upstream_actions

            full_content: dict[str, Any] = {}
            for act in merge_actions:
                act_deltas = upstream.get(act, {})
                if not act_deltas:
                    continue
                delta_content = act_deltas.get(guid) if guid else None
                if delta_content is None:
                    # Upstream has data for this file but not this guid.
                    # Could be routing/partitioning (action processes a
                    # subset of guids) — log at debug, not warning.
                    logger.debug(
                        "Record %s not found in upstream '%s' — may be partitioned.",
                        guid,
                        act,
                    )
                else:
                    full_content.update(delta_content)

            current_content = record.get("content")
            if current_content is not None:
                full_content.update(current_content)
            else:
                logger.error("Delta record %s in '%s' has no content key.", guid, action_name)

            full_record = {k: v for k, v in record.items() if k != "content" and k != "_delta_mode"}
            full_record["content"] = full_content

            reconstructed.append(full_record)

        return reconstructed

    def _get_upstream_actions(self, action_name: str) -> list[str]:
        """Get the transitive upstream actions for a given action.

        Uses the dependency graph if available (correct for DAGs with parallel actions).
        Falls back to execution_order[:idx] if no graph stored (legacy).
        """
        # Try dependency graph first (correct for parallel pipelines)
        if self._dependency_graph_cache is None:
            raw = self.load_metadata("dependency_graph")
            if raw is not None:
                try:
                    self._dependency_graph_cache = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning(
                        "Corrupt dependency_graph in metadata — reconstruction will use flat fallback."
                    )
                    self._dependency_graph_cache = {}
            else:
                self._dependency_graph_cache = {}

        if self._dependency_graph_cache and action_name in self._dependency_graph_cache:
            return self._dependency_graph_cache[action_name]

        if self._dependency_graph_cache and action_name not in self._dependency_graph_cache:
            logger.warning(
                "Action '%s' not found in dependency graph — using flat execution order fallback. "
                "This may include parallel peers as upstream.",
                action_name,
            )

        execution_order = self._get_execution_order()
        try:
            idx = execution_order.index(action_name)
        except ValueError:
            return []
        return execution_order[:idx]

    def _get_execution_order(self) -> list[str]:
        """Get the workflow execution order from metadata. Cached per instance."""
        if self._execution_order_cache is not None:
            return self._execution_order_cache
        raw = self.load_metadata("execution_order")
        if raw is None:
            return []
        try:
            self._execution_order_cache = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Corrupt execution_order in metadata — delta reconstruction disabled.")
            return []
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
    def claim_source_guid_for_run(self, source_guid: str, relative_path: str) -> bool:
        """Claim source_guid for this run under relative_path; True if taken elsewhere.

        In-memory, never persisted — a persisted check can't tell a still-live
        duplicate from this file's own row before it was renamed. Scoped by
        relative_path, not action_name: independent start-node actions share one
        staging directory by default, so the same file is legitimately claimed
        more than once per run — only a DIFFERENT relative_path claiming the
        same guid is the real duplicate-content case.
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

    def set_disposition(
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
        raise NotImplementedError
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

    def source_files_for_records(self, record_ids: Iterable[str]) -> set[str]:
        """Staging paths, suffix stripped, of the files holding *record_ids*.

        Empty when nothing is known: a caller narrowing a walk to these files must
        treat that as "cannot resolve" and walk everything, or a retry whose source
        rows were pruned would process no file at all.
        """
        return set()

    def records_share_a_repeat_chain(self, record_ids: Iterable[str]) -> bool:
        """Whether any of record_ids is a repeat, or is repeated by another row.

        A repair narrowed to just the file(s) naming record_ids would then lack
        the sibling file(s) identity re-derivation needs to reproduce the same
        guid — the caller falls back to an unnarrowed walk when this is True.
        Defaults True (unknown treated as sharing) — same safe-by-default
        posture as `source_files_for_records`'s empty-means-walk-everything.
        """
        return True

    def clear_disposition(
        self,
        action_name: str,
        disposition: str | None = None,
        record_id: str | None = None,
    ) -> int:
        """Delete matching disposition records. Returns count deleted."""
        return 0

    def save_checkpoint_records(
        self,
        action_name: str,
        relative_path: str,
        records: list[dict[str, Any]],
    ) -> None:
        """Upsert records into the checkpoint output table.

        Used for incremental checkpointing during online processing.
        Uses INSERT OR REPLACE keyed on (action_name, relative_path, source_guid).
        """
        raise NotImplementedError

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
        source_guid: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Persist the compiled prompt and LLM context for a single record.

        ``record_id`` holds the prepare-time target_id; ``source_guid`` is the
        durable identity joins key on. This is telemetry. Implementations
        should not raise on failure.
        """

    def update_prompt_trace_response(  # noqa: B027
        self,
        action_name: str,
        record_id: str,
        response_text: str,
        parent_record_id: str | None = None,
    ) -> None:
        """Attach the LLM response to the newest trace row for a prepared task.

        Pass ``parent_record_id`` when the record may be an expansion child,
        whose own id was minted after its prompt ran.

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

    def clear_batch_state(self, action_name: str) -> None:
        """Delete all batch state (registry, recovery, context) for an action."""
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

        self.delete_metadata(f"{BatchRegistryManager.METADATA_KEY_PREFIX}{action_name}")
        self.delete_metadata_prefix(f"recovery_state:{action_name}:")
        self.delete_metadata_prefix(f"batch_context:{action_name}:")

    def scan_data(self, preview_limit: int = 20) -> dict[str, Any] | None:
        """Return stats and preview records for the docs scanner.

        Default returns None. Backends override to provide scan capability.
        """
        return None

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

    @classmethod
    def paths_to_wipe(cls, io_dir: Path) -> list[Path]:
        """Paths under ``io_dir`` this backend owns and ``clean --all`` should remove.

        Default is empty — remote backends (Postgres, S3) own no local
        filesystem paths and are not touched by ``clean --all``. File-based
        backends (SQLite, DuckDB) override to name their owned directories so
        the CLI lists, confirms, and deletes them uniformly regardless of
        which backend is configured.
        """
        return []

    def close(self) -> None:  # noqa: B027
        """Close the storage backend and release resources."""
        self._reconstruction_cache.clear()
        self._execution_order_cache = None
        self._dependency_graph_cache = None

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
