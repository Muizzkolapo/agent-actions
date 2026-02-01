"""Module for loading historical node data from target files using lineage tracking."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any
from agent_actions.cli.utils.service_logger import ServiceLogger

logger = logging.getLogger(__name__)

# Maximum directory depth to search for SQLite database
_MAX_SQLITE_SEARCH_DEPTH = 5


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
            ServiceLogger.log_operation_start(
                logger,
                "load historical node data",
                action_name=request.action_name,
                source_guid=request.source_guid,
            )

            # Find the node_id in lineage for this action
            # If not found, this may be a parallel sibling (ancestry matching case)
            logger.debug(
                "[DEBUG] Finding node_id for action='%s' in lineage=%s",
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
                    "[DEBUG] Node not in lineage for action '%s' - trying ancestry matching. "
                    "parent_target_id=%s, root_target_id=%s",
                    request.action_name,
                    request.parent_target_id,
                    request.root_target_id,
                )
            else:
                logger.debug(
                    "[DEBUG] Found node_id=%s for action='%s'", node_id, request.action_name
                )

            # Get the node index for constructing the path
            node_idx = request.agent_indices.get(request.action_name)
            if node_idx is None:
                logger.warning(
                    "No index found for action '%s' in agent_indices", request.action_name
                )
                return None

            # Construct path to the target file
            target_path = HistoricalNodeDataLoader._construct_target_path(
                request.action_name, node_idx, request.file_path
            )
            logger.debug(
                "[DEBUG HISTORICAL] action_name=%s, file_path=%s -> target_path=%s",
                request.action_name,
                request.file_path,
                target_path,
            )

            if not target_path.exists():
                # Try SQLite fallback - find database in target directory
                data = HistoricalNodeDataLoader._try_load_from_sqlite(
                    request.action_name,
                    Path(request.file_path).name,
                    request.output_directory,
                )
                if data is None:
                    logger.warning("Target file does not exist and no SQLite fallback: %s", target_path)
                    return None
            else:
                # Load from JSON file
                logger.debug("[DEBUG] Loading file: %s", target_path)
                with open(target_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

            logger.debug("[DEBUG] File loaded, %s records found", len(data))

            # DEBUG: Log what we're searching for
            lineage_status = "provided" if request.caller_lineage else "None"
            logger.debug(
                "[DEBUG] Searching for record: source_guid=%s, node_id=%s, caller_lineage=%s, "
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

            # DEBUG: Log result
            if record:
                content = record.get("content", {})
                content_keys = list(content.keys()) if isinstance(content, dict) else []
                logger.debug(
                    "[DEBUG HISTORICAL] Found record for action '%s': node_id=%s, content_keys=%s",
                    request.action_name,
                    record.get("node_id"),
                    content_keys,
                )
                ServiceLogger.log_operation_success(
                    logger,
                    "load historical node data",
                    action_name=request.action_name,
                    node_id=node_id,
                )
                return content

            source_guids = set(r.get("source_guid") for r in data if isinstance(r, dict))
            logger.debug("[DEBUG] No match found. File contains source_guids: %s", source_guids)
            logger.warning(
                "No record found for source_guid=%s, node_id=%s in %s",
                request.source_guid,
                node_id,
                target_path,
            )
            return None

        except (ValueError, TypeError, KeyError) as e:
            ServiceLogger.log_operation_error(logger, "load historical node data", e)
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
    def _construct_target_path(action_name: str, node_idx: int, current_file_path: str) -> Path:
        """
        Construct the path to the target file for the given action.

        Args:
            action_name: Name of the action/agent
            node_idx: Node index (kept for API compatibility, not used for path)
            current_file_path: Current file being processed

        Returns:
            Path to the target file

        Example:
            action_name = "fact_extractor"
            current_file_path = "target/cluster/file.json"

            Returns: Path("target/fact_extractor/file.json")
        """
        current_path = Path(current_file_path)
        file_name = current_path.name

        # Navigate to the target directory root
        # Structure: target/{action_name}/file.json
        target_root = current_path.parent.parent

        # Use simple directory name (no index prefix)
        target_dir = target_root / action_name
        target_file = target_dir / file_name

        return target_file

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
            logger.debug("[DEBUG _find_record] Data is not a list, type=%s", type(data))
            return None

        logger.debug(
            "[DEBUG _find_record] Searching %s records for source_guid=%s, "
            "parent_target_id=%s, is_parallel_sibling=%s, action_name=%s",
            len(data),
            source_guid,
            parent_target_id,
            is_parallel_sibling,
            action_name,
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
                "[DEBUG _find_record] Match #%s: node_id=%s, parent_target_id=%s, root_target_id=%s",
                matches_found,
                record.get("node_id"),
                record.get("parent_target_id"),
                record.get("root_target_id"),
            )

            # Strategy 1: Lineage matching (for direct ancestors, not parallel siblings)
            if not is_parallel_sibling and caller_lineage is not None:
                record_lineage = record.get("lineage")
                if HistoricalNodeDataLoader._lineages_match(record_lineage, caller_lineage):
                    logger.debug("[DEBUG _find_record] Lineage match found")
                    return record

            # Strategy 2: Parent matching (for parallel siblings - Diamond pattern)
            if parent_target_id and record.get("parent_target_id") == parent_target_id:
                if parent_match is None:
                    parent_match = record
                    logger.debug("[DEBUG _find_record] Parent match found")

            # Strategy 3: Root matching (for Map-Reduce aggregation)
            if root_target_id and record.get("root_target_id") == root_target_id:
                if root_match is None:
                    root_match = record
                    logger.debug("[DEBUG _find_record] Root match found")

        # Return based on priority
        if is_parallel_sibling:
            # For parallel siblings, prefer ancestry matching strategies
            if parent_match:
                logger.debug("[DEBUG _find_record] Returning parent_target_id match")
                return parent_match
            if root_match:
                logger.debug("[DEBUG _find_record] Returning root_target_id match")
                return root_match
            # Fallback: return first source_guid match (for Action 0 parallel siblings
            # that have no parent_target_id because they process original source data)
            if first_match:
                logger.debug(
                    "[DEBUG _find_record] Returning source_guid fallback match "
                    "(parallel sibling with no parent/root ancestry)"
                )
                return first_match

        logger.debug(
            "[DEBUG _find_record] No matches found (searched %s records)",
            len(data),
        )
        return None

    @staticmethod
    def _try_load_from_sqlite(
        action_name: str, filename: str, output_directory: Optional[str] = None
    ) -> Optional[List[Dict]]:
        """
        Try to load historical data from SQLite database.

        Searches for a .db file in standard workflow locations and queries
        the target_data table for the specified action.

        Args:
            action_name: Name of the action to load data for
            filename: Original filename (e.g., "books_sample.json")
            output_directory: Optional output directory path for database lookup

        Returns:
            List of records from SQLite, or None if not found
        """
        import sqlite3
        from pathlib import Path
        import os

        search_patterns = []

        # First priority: derive from output_directory if provided
        if output_directory:
            output_path = Path(output_directory)
            # Output directory is typically: .../agent_io/target/{action_name}
            # Database is at: .../agent_io/target/{workflow_name}.db
            if "target" in output_path.parts:
                target_idx = list(output_path.parts).index("target")
                target_dir = Path(*output_path.parts[: target_idx + 1])
                if target_dir.exists():
                    search_patterns.append(target_dir)

        # Fallback: check current working directory structure
        cwd = Path(os.getcwd())

        # Check multiple levels up (bounded by constant)
        current = cwd
        for _ in range(_MAX_SQLITE_SEARCH_DEPTH):
            target_dir = current / "agent_io" / "target"
            if target_dir.exists() and target_dir not in search_patterns:
                search_patterns.append(target_dir)
            current = current.parent
            if current == current.parent:  # Reached filesystem root
                break

        # Search for .db files in discovered directories
        for pattern_base in search_patterns:
            if not pattern_base.exists():
                continue
            for db_file in pattern_base.glob("*.db"):
                conn = None
                try:
                    conn = sqlite3.connect(str(db_file), timeout=5.0)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()

                    # Query for the action's data
                    cursor.execute(
                        "SELECT data FROM target_data WHERE node_name = ? AND relative_path = ?",
                        (action_name, filename),
                    )
                    row = cursor.fetchone()

                    if row:
                        data = json.loads(row["data"])
                        logger.debug(
                            "[SQLite FALLBACK] Loaded %d records for %s from %s",
                            len(data) if isinstance(data, list) else 1,
                            action_name,
                            db_file,
                        )
                        return data if isinstance(data, list) else [data]
                except sqlite3.Error as e:
                    logger.warning(
                        "[SQLite FALLBACK] Database error loading from %s: %s",
                        db_file,
                        e,
                    )
                except json.JSONDecodeError as e:
                    logger.warning(
                        "[SQLite FALLBACK] JSON decode error for %s in %s: %s",
                        action_name,
                        db_file,
                        e,
                    )
                finally:
                    if conn is not None:
                        conn.close()

        logger.debug("[SQLite FALLBACK] No database found for action %s", action_name)
        return None
