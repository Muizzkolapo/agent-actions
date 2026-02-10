"""Module for loading historical node data from storage backend using lineage tracking."""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


@dataclass
class HistoricalDataRequest:
    """Request parameters for loading historical node data.

    Supports Ancestry Chain pattern for parallel branch merging:
    - parent_target_id: Links to immediate parent (Diamond/Fan-in patterns)
    - root_target_id: Links to original ancestor (Map-Reduce patterns)
    """

    action_name: str
    lineage: List[str]
    source_guid: str
    file_path: str
    agent_indices: Dict[str, int]
    caller_lineage: Optional[List[str]] = None
    # Ancestry Chain fields (RFC: docs/specs/RFC_ancestry_chain.md)
    parent_target_id: Optional[str] = None
    root_target_id: Optional[str] = None
    # Output directory for SQLite fallback (optional)
    output_directory: Optional[str] = None
    # Storage backend for querying from SQLite/TinyDB
    storage_backend: Optional["StorageBackend"] = None


class HistoricalNodeDataLoader:
    """
    Loads historical node data from target directories using lineage tracking.

    This class enables referencing upstream agent outputs using {action_name.field}
    syntax by finding and loading the appropriate target file based on lineage.
    """

    def __repr__(self):
        """Return string representation of HistoricalNodeDataLoader."""
        return f"{self.__class__.__name__}()"

    @staticmethod
    def load_historical_node_data(request: HistoricalDataRequest) -> Optional[Dict[str, Any]]:
        """
        Load historical node data for a specific action from target files.

        Args:
            request: HistoricalDataRequest containing all parameters

        Returns:
            Content dict from the historical node, or None if not found

        Example:
            request = HistoricalDataRequest(
                action_name="fact_extractor",
                lineage=["node_0_abc123", "node_1_def456"],
                source_guid="guid-123",
                file_path="/path/to/file.json",
                agent_indices={"fact_extractor": 0, "flatten_facts": 1}
            )

            Returns content from target/node_0_fact_extractor/file.json
            where record matches source_guid and node_id="node_0_abc123"
        """
        try:
            logger.debug(
                "Starting load historical node data",
                extra={
                    "operation": "load historical node data",
                    "action_name": request.action_name,
                    "source_guid": request.source_guid,
                },
            )

            # Find the node_id in lineage for this action
            # If not found, this may be a parallel sibling (ancestry matching case)
            logger.debug(
                "Finding node_id for action='%s' in lineage=%s",
                request.action_name,
                request.lineage,
            )
            node_id = HistoricalNodeDataLoader._find_node_in_lineage(
                request.action_name, request.lineage, request.agent_indices
            )

            # Determine if this is a parallel sibling case (node not in lineage)
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

            # Storage backend is required for historical data loading
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
                content = record.get("content", {})
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

        except (ValueError, TypeError, KeyError) as e:
            logger.error(
                "Failed to load historical node data: %s",
                str(e),
                extra={"operation": "load historical node data", "error": str(e)},
            )
            # Don't raise - return None to allow processing to continue
            return None

    @staticmethod
    def _find_node_in_lineage(
        action_name: str, lineage: List[str], agent_indices: Dict[str, int]
    ) -> Optional[str]:
        """
        Find the node_id in lineage that corresponds to the given action.

        Args:
            action_name: Name of the action/agent
            lineage: List of node_ids
            agent_indices: Mapping of agent names to node indices (kept for API compatibility)

        Returns:
            The matching node_id or None if not found

        Example:
            action_name = "fact_extractor"
            lineage = ["fact_extractor_abc123", "flatten_facts_def456"]

            Returns: "fact_extractor_abc123" (matches action name prefix)
        """
        if not lineage:
            return None

        # Node IDs now use format: {action_name}_{uuid}
        node_prefix = f"{action_name}_"

        # Find the node_id that starts with the action name
        for node_id in lineage:
            if isinstance(node_id, str) and node_id.startswith(node_prefix):
                return node_id

        return None

    @staticmethod
    def _load_from_storage_backend(
        storage_backend: "StorageBackend",
        action_name: str,
        file_path: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Load target data from the storage backend.

        Args:
            storage_backend: Storage backend instance (SQLite, TinyDB, etc.)
            action_name: Name of the action/node to load from
            file_path: Current file path (used to derive relative_path)

        Returns:
            List of records from storage, or None if not found
        """
        from pathlib import Path as PathLib

        file_name = PathLib(file_path).name  # e.g., "batch_0.json" from ".../batch_0.json"

        try:
            # First try: load with the derived file name (fast path)
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
            # File name doesn't match - search across all files for this action
            # This handles workflows where file names change between stages
            # (e.g., aggregation, flattening, fan-in patterns)
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

                # Load and combine records from all files
                all_records: List[Dict[str, Any]] = []
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
    def _lineages_match(
        record_lineage: Optional[List[str]], caller_lineage: Optional[List[str]]
    ) -> bool:
        """
        Check if record's lineage is a prefix of caller's lineage.

        For split records scenarios, a record from node_5 may have lineage:
            [node_0, node_1, node_4, node_5, node_6_branch_a]

        A caller from node_23 in the same branch would have lineage:
            [node_0, node_1, node_4, node_5, node_6_branch_a, ..., node_23]

        The record's lineage must be a PREFIX of the caller's lineage for a match.

        Args:
            record_lineage: Lineage from the historical record
            caller_lineage: Lineage from the current record looking up historical data

        Returns:
            True if record's lineage is a prefix of caller's lineage, False otherwise

        Examples:
            >>> _lineages_match(
            ...     ['node_0', 'node_1', 'node_5', 'node_6_a'],
            ...     ['node_0', 'node_1', 'node_5', 'node_6_a', 'node_23']
            ... )
            True

            >>> _lineages_match(
            ...     ['node_0', 'node_1', 'node_5', 'node_6_b'],
            ...     ['node_0', 'node_1', 'node_5', 'node_6_a', 'node_23']
            ... )
            False

            >>> _lineages_match(None, ['node_0', 'node_1'])
            False
        """
        # Handle None/empty cases
        if not record_lineage or not caller_lineage:
            return False

        # Record lineage cannot be longer than caller lineage
        if len(record_lineage) > len(caller_lineage):
            return False

        # Check if record's lineage is a prefix of caller's lineage
        return record_lineage == caller_lineage[: len(record_lineage)]

    @staticmethod
    def _find_record_by_identifiers(
        data: List[Dict],
        source_guid: str,
        _node_id: str,
        caller_lineage: Optional[List[str]] = None,
        parent_target_id: Optional[str] = None,
        root_target_id: Optional[str] = None,
        is_parallel_sibling: bool = False,
        action_name: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Find a record in the data using multi-strategy matching.

        **Matching Priority** (RFC: docs/specs/RFC_ancestry_chain.md):
        1. Lineage match (existing behavior) - for direct ancestors
        2. Parent match (parent_target_id) - for parallel siblings (Diamond pattern)
        3. Root match (root_target_id) - for Map-Reduce aggregation

        **Scenarios Handled**:
        - Direct ancestors: Uses lineage prefix matching
        - Parallel siblings: Uses parent_target_id (Diamond/Fan-in)
        - Map-Reduce: Uses root_target_id
        - Granularity changes: Requires ancestry fields for disambiguation

        Args:
            data: List of records from the target file
            source_guid: Source GUID to match (required)
            _node_id: Node ID (kept for logging/diagnostics)
            caller_lineage: Optional lineage for prefix matching
            parent_target_id: Optional parent ID for sibling matching
            root_target_id: Optional root ID for Map-Reduce matching
            is_parallel_sibling: True if dependency node is not in caller's lineage
            action_name: Optional action name to filter by node_id prefix

        Returns:
            The matching record or None if not found
        """
        if not isinstance(data, list):
            logger.debug("Data is not a list, type=%s", type(data))
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
                continue

            # Primary filter: source_guid
            if record.get("source_guid") != source_guid:
                continue

            # Secondary filter: node_id must contain action_name
            # This prevents returning records from wrong actions that happen to share source_guid
            # Supports both formats:
            #   - Production: "{action_name}_{uuid}" (e.g., "get_authoring_prompt_abc123")
            #   - Test/legacy: "node_{idx}_{action_name}" (e.g., "node_4_generate_seo")
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

            # Strategy 1: Lineage matching (for direct ancestors, not parallel siblings)
            if not is_parallel_sibling and caller_lineage is not None:
                record_lineage = record.get("lineage")
                if HistoricalNodeDataLoader._lineages_match(record_lineage, caller_lineage):
                    logger.debug("Lineage match found")
                    return record

            # Strategy 2: Parent matching (for parallel siblings - Diamond pattern)
            if parent_target_id and record.get("parent_target_id") == parent_target_id:
                if parent_match is None:
                    parent_match = record
                    logger.debug("Parent match found")

            # Strategy 3: Root matching (for Map-Reduce aggregation)
            if root_target_id and record.get("root_target_id") == root_target_id:
                if root_match is None:
                    root_match = record
                    logger.debug("Root match found")

        # Return based on priority
        if is_parallel_sibling:
            # For parallel siblings, prefer ancestry matching strategies
            if parent_match:
                logger.debug("[HISTORICAL] Returning parent_target_id match")
                return parent_match
            if root_match:
                logger.debug("[HISTORICAL] Returning root_target_id match")
                return root_match
            # Fallback: return first source_guid match (for Action 0 parallel siblings
            # that have no parent_target_id because they process original source data)
            if first_match:
                logger.debug("[HISTORICAL] Returning source_guid fallback match (parallel sibling)")
                return first_match

        logger.debug("[HISTORICAL] No matches found (searched %d records)", len(data))
        return None
