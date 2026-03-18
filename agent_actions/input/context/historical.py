"""Historical node data loading from storage backend using lineage tracking."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

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
    source_guid: str
    file_path: str
    agent_indices: dict[str, int]
    caller_lineage: list[str] | None = None
    # Ancestry Chain fields (RFC: docs/specs/RFC_ancestry_chain.md)
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

        logger.debug(
            "Finding node_id for action='%s' in lineage=%s",
            request.action_name,
            request.lineage,
        )
        node_id = HistoricalNodeDataLoader._find_node_in_lineage(
            request.action_name, request.lineage, request.agent_indices
        )

        is_parallel_sibling = node_id is None

        if is_parallel_sibling:
            logger.debug(
                "Node not in lineage for action '%s' - trying ancestry matching. "
                "parent_target_id=%s, root_target_id=%s",
                request.action_name,
                request.parent_target_id,
                request.root_target_id,
            )
        else:
            logger.debug("Found node_id=%s for action='%s'", node_id, request.action_name)

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

        lineage_status = "provided" if request.caller_lineage else "None"
        logger.debug(
            "Searching for record: source_guid=%s, node_id=%s, caller_lineage=%s, "
            "parent_target_id=%s, root_target_id=%s",
            request.source_guid,
            node_id,
            lineage_status,
            request.parent_target_id,
            request.root_target_id,
        )

        record = HistoricalNodeDataLoader._find_record_by_identifiers(
            data,
            request.source_guid,
            node_id,
            request.caller_lineage,
            parent_target_id=request.parent_target_id,
            root_target_id=request.root_target_id,
            is_parallel_sibling=is_parallel_sibling,
            action_name=request.action_name,
        )

        if record:
            content: dict[str, Any] = record.get("content", {})
            content_keys = list(content.keys()) if isinstance(content, dict) else []
            logger.debug(
                "[HISTORICAL] Found record for action '%s': node_id=%s, content_keys=%s",
                request.action_name,
                record.get("node_id"),
                content_keys,
            )
            logger.debug(
                "Successfully completed load historical node data",
                extra={
                    "operation": "load historical node data",
                    "action_name": request.action_name,
                    "node_id": node_id,
                },
            )
            return content

        source_guids = set(r.get("source_guid") for r in data if isinstance(r, dict))
        logger.debug("No match found. File contains source_guids: %s", source_guids)
        logger.warning(
            "No record found for source_guid=%s, node_id=%s in action '%s'",
            request.source_guid,
            node_id,
            request.action_name,
        )
        return None

    @staticmethod
    def _find_node_in_lineage(
        action_name: str, lineage: list[str], agent_indices: dict[str, int]
    ) -> str | None:
        """Find the node_id in lineage that corresponds to the given action."""
        if not lineage:
            return None

        node_prefix = f"{action_name}_"

        for node_id in lineage:
            if isinstance(node_id, str) and node_id.startswith(node_prefix):
                return node_id

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
    def _lineages_match(record_lineage: list[str] | None, caller_lineage: list[str] | None) -> bool:
        """Check if record's lineage is a prefix of caller's lineage.

        Example: record lineage [A, B, C] matches caller lineage [A, B, C, D, E]
        but not [A, B, X, D, E] (diverged branch).
        """
        if not record_lineage or not caller_lineage:
            return False

        if len(record_lineage) > len(caller_lineage):
            return False

        return record_lineage == caller_lineage[: len(record_lineage)]

    @staticmethod
    def _find_record_by_identifiers(
        data: list[dict],
        source_guid: str,
        _node_id: str | None,
        caller_lineage: list[str] | None = None,
        parent_target_id: str | None = None,
        root_target_id: str | None = None,
        is_parallel_sibling: bool = False,
        action_name: str | None = None,
    ) -> dict | None:
        """Find a record using multi-strategy matching (RFC: docs/specs/RFC_ancestry_chain.md).

        Priority: lineage prefix match > parent_target_id (Diamond) > root_target_id (Map-Reduce).
        For parallel siblings (node not in lineage), ancestry fields are used instead.
        """
        if not isinstance(data, list):
            logger.debug("Data is not a list, type=%s", type(data))  # type: ignore[unreachable]
            return None

        logger.debug(
            "[HISTORICAL] Searching %d records for source_guid=%s, action_name=%s, is_parallel_sibling=%s",
            len(data),
            source_guid,
            action_name,
            is_parallel_sibling,
        )

        matches_found = 0
        parent_match = None
        root_match = None
        first_match = None  # Fallback for source_guid-only match

        for record in data:
            if not isinstance(record, dict):
                continue  # type: ignore[unreachable]

            if record.get("source_guid") != source_guid:
                continue

            # Prevents wrong-action matches: supports both "{action}_{uuid}" and "node_{idx}_{action}"
            record_node_id = record.get("node_id", "")
            if action_name and action_name not in record_node_id:
                continue

            matches_found += 1
            if first_match is None:
                first_match = record  # Track first source_guid match as fallback

            logger.debug(
                "Match #%s: node_id=%s, parent_target_id=%s, root_target_id=%s",
                matches_found,
                record.get("node_id"),
                record.get("parent_target_id"),
                record.get("root_target_id"),
            )

            if not is_parallel_sibling and caller_lineage is not None:
                record_lineage = record.get("lineage", [])
                if record_lineage and HistoricalNodeDataLoader._lineages_match(record_lineage, caller_lineage):
                    logger.debug("Lineage match found")
                    return record

            if parent_target_id and record.get("parent_target_id") == parent_target_id:
                if parent_match is None:
                    parent_match = record
                    logger.debug("Parent match found")

            if root_target_id and record.get("root_target_id") == root_target_id:
                if root_match is None:
                    root_match = record
                    logger.debug("Root match found")

        if is_parallel_sibling:
            if parent_match:
                logger.debug("[HISTORICAL] Returning parent_target_id match")
                return parent_match
            if root_match:
                logger.debug("[HISTORICAL] Returning root_target_id match")
                return root_match
            # Action 0 parallel siblings have no parent_target_id
            if first_match:
                logger.debug("[HISTORICAL] Returning source_guid fallback match (parallel sibling)")
                return first_match

        logger.debug("[HISTORICAL] No matches found (searched %d records)", len(data))
        return None
