"""Historical node data loading from storage backend using lineage tracking."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from agent_actions.prompt.context.scope_namespace import _extract_content_data

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


@dataclass
class HistoricalDataRequest:
    """Request parameters for loading historical node data.

    Ancestry Chain fields (parent_target_id, root_target_id) support parallel
    branch merging — see docs/specs/RFC_ancestry_chain.md.
    """

    action_name: str
    lineage: list[str]
    source_guid: str  # Kept for logging/diagnostics, NOT for matching
    file_path: str
    agent_indices: dict[str, int]
    lineage_sources: list[str] | None = None  # For merge-parent mode
    # Ancestry Chain fields — metadata only, not used for matching
    parent_target_id: str | None = None
    root_target_id: str | None = None
    # Output directory for SQLite fallback (optional)
    output_directory: str | None = None
    # Storage backend for querying from SQLite/TinyDB
    storage_backend: Optional["StorageBackend"] = None


class HistoricalNodeDataLoader:
    """Loads historical node data from target directories using lineage tracking."""

    def __repr__(self):
        return f"{self.__class__.__name__}()"

    @staticmethod
    def load_historical_node_data(request: HistoricalDataRequest) -> dict[str, Any] | None:
        """Load historical node data for a specific action. Returns content dict or None."""
        logger.debug(
            "Starting load historical node data",
            extra={
                "operation": "load historical node data",
                "action_name": request.action_name,
                "source_guid": request.source_guid,
            },
        )

        target_node_id = HistoricalNodeDataLoader._find_target_node_id(
            action_name=request.action_name,
            lineage=request.lineage,
            lineage_sources=request.lineage_sources,
            agent_indices=request.agent_indices,
        )

        if target_node_id is None:
            logger.warning(
                "[HISTORICAL] No node_id found for action '%s' in lineage=%s, lineage_sources=%s",
                request.action_name,
                request.lineage,
                request.lineage_sources,
            )
            return None

        logger.debug(
            "Found target_node_id=%s for action='%s'",
            target_node_id,
            request.action_name,
        )

        if request.storage_backend is None:
            logger.warning(
                "[HISTORICAL] No storage backend provided for action '%s'",
                request.action_name,
            )
            return None

        data = HistoricalNodeDataLoader._load_from_storage_backend(
            request.storage_backend,
            request.action_name,
            request.file_path,
        )
        if data is None:
            logger.debug(
                "[HISTORICAL] No data in storage backend for '%s'",
                request.action_name,
            )
            return None

        logger.debug("[HISTORICAL] Loaded %d records for %s", len(data), request.action_name)

        record = HistoricalNodeDataLoader._find_record_by_identifiers(
            data,
            target_node_id,
            request.action_name,
        )

        if record:
            content: dict[str, Any] = _extract_content_data(record)
            content_keys = list(content.keys()) if isinstance(content, dict) else []
            logger.debug(
                "[HISTORICAL] Found record for action '%s': node_id=%s, content_keys=%s",
                request.action_name,
                record.get("node_id"),
                content_keys,
            )
            return content

        return None

    @staticmethod
    def _load_from_storage_backend(
        storage_backend: "StorageBackend",
        action_name: str,
        file_path: str,
    ) -> list[dict[str, Any]] | None:
        """Load target data from the storage backend."""
        from pathlib import Path as PathLib

        file_name = PathLib(file_path).name

        try:
            logger.debug(
                "[STORAGE_BACKEND] Loading from storage: action_name=%s, relative_path=%s",
                action_name,
                file_name,
            )
            data = storage_backend.read_target(
                action_name=action_name,
                relative_path=file_name,
            )
            logger.debug(
                "[STORAGE_BACKEND] Loaded %d records for %s/%s",
                len(data) if data else 0,
                action_name,
                file_name,
            )
            return data
        except FileNotFoundError:
            # File names may change between stages (aggregation, fan-in, etc.)
            logger.debug(
                "[STORAGE_BACKEND] File %s not found for %s, searching all files",
                file_name,
                action_name,
            )
            try:
                all_files = storage_backend.list_target_files(action_name)
                if not all_files:
                    logger.debug(
                        "[STORAGE_BACKEND] No files found for action %s",
                        action_name,
                    )
                    return None

                all_records: list[dict[str, Any]] = []
                for f in all_files:
                    try:
                        records = storage_backend.read_target(action_name, f)
                        if records:
                            all_records.extend(records)
                    except Exception as e:
                        logger.debug(
                            "[STORAGE_BACKEND] Error reading %s/%s: %s",
                            action_name,
                            f,
                            e,
                        )

                logger.debug(
                    "[STORAGE_BACKEND] Loaded %d total records from %d files for %s",
                    len(all_records),
                    len(all_files),
                    action_name,
                )
                return all_records if all_records else None
            except Exception as e:
                logger.warning(
                    "[STORAGE_BACKEND] Error listing files for %s: %s",
                    action_name,
                    e,
                )
                return None
        except Exception as e:
            logger.warning(
                "[STORAGE_BACKEND] Error loading from storage backend: %s",
                e,
            )
            return None

    @staticmethod
    def _find_target_node_id(
        action_name: str,
        lineage: list[str],
        lineage_sources: list[str] | None = None,
        agent_indices: dict[str, int] | None = None,
    ) -> str | None:
        """Extract the target action's node_id from lineage metadata.

        Mode 1 (Ancestor): Target action's node_id is in the lineage chain.
        Mode 2 (Merge parent): Target action's node_id is in lineage_sources.

        Uses agent_indices to disambiguate prefix collisions (e.g., 'extract'
        vs 'extract_raw_qa'). Longest matching action name wins.
        """
        all_action_names = set(agent_indices.keys()) if agent_indices else set()

        def _is_exact_owner(nid: str) -> bool:
            prefix = f"{action_name}_"
            if not nid.startswith(prefix):
                return False
            for other in all_action_names:
                if (
                    other != action_name
                    and len(other) > len(action_name)
                    and nid.startswith(f"{other}_")
                ):
                    return False
            return True

        # Mode 1: Ancestor
        for node_id in lineage:
            if isinstance(node_id, str) and _is_exact_owner(node_id):
                return node_id

        # Mode 2: Merge parent
        if lineage_sources:
            for node_id in lineage_sources:
                if isinstance(node_id, str) and _is_exact_owner(node_id):
                    return node_id

        return None

    @staticmethod
    def _find_record_by_identifiers(
        data: list[dict],
        target_node_id: str,
        action_name: str,
    ) -> dict | None:
        """Find a record by exact node_id match.

        Beam-style deterministic key join. No fallbacks.
        Returns exact match or None.
        """
        if not isinstance(data, list):
            return None  # type: ignore[unreachable]

        for record in data:
            if not isinstance(record, dict):
                continue  # type: ignore[unreachable]
            if record.get("node_id") == target_node_id:
                return record

        logger.warning(
            "[HISTORICAL] No record with node_id=%s in action '%s' (%d records searched)",
            target_node_id,
            action_name,
            len(data),
        )
        return None
