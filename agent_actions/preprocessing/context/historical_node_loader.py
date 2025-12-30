"""Module for loading historical node data from target files using lineage tracking."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any
from agent_actions.cli.utils.service_logger import ServiceLogger

logger = logging.getLogger(__name__)


@dataclass
class HistoricalDataRequest:
    """Request parameters for loading historical node data."""

    action_name: str
    lineage: List[str]
    source_guid: str
    file_path: str
    agent_indices: Dict[str, int]
    caller_lineage: Optional[List[str]] = None


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

            # Find the node_id in lineage for this action (used for diagnostics and logging)
            # NOTE: This is no longer used for matching in _find_record_by_identifiers,
            # but we keep it for logging and debugging purposes
            logger.debug(
                "[DEBUG] Finding node_id for action='%s' in lineage=%s",
                request.action_name,
                request.lineage,
            )
            node_id = HistoricalNodeDataLoader._find_node_in_lineage(
                request.action_name, request.lineage, request.agent_indices
            )

            if not node_id:
                logger.warning(
                    "[DEBUG] No node_id found in lineage for action '%s'. Lineage: %s",
                    request.action_name,
                    request.lineage,
                )
                return None

            logger.debug("[DEBUG] Found node_id=%s for action='%s'", node_id, request.action_name)

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

            if not target_path.exists():
                logger.warning("Target file does not exist: %s", target_path)
                return None

            # Load and find the record
            logger.debug("[DEBUG] Loading file: %s", target_path)
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            logger.debug("[DEBUG] File loaded, %s records found", len(data))

            # DEBUG: Log what we're searching for
            lineage_status = "provided" if request.caller_lineage else "None"
            logger.debug(
                "[DEBUG] Searching for record: source_guid=%s, node_id=%s, caller_lineage=%s",
                request.source_guid,
                node_id,
                lineage_status,
            )

            record = HistoricalNodeDataLoader._find_record_by_identifiers(
                data, request.source_guid, node_id, request.caller_lineage
            )

            # DEBUG: Log result
            if record:
                logger.debug("[DEBUG] Found record with node_id=%s", record.get("node_id"))
                ServiceLogger.log_operation_success(
                    logger,
                    "load historical node data",
                    action_name=request.action_name,
                    node_id=node_id,
                )
                return record.get("content")

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
            agent_indices: Mapping of agent names to node indices

        Returns:
            The matching node_id or None if not found

        Example:
            action_name = "fact_extractor"
            lineage = ["node_0_abc123", "node_1_def456", "node_2_ghi789"]
            agent_indices = {"fact_extractor": 0, "flatten_facts": 1}

            Returns: "node_0_abc123" (matches node_0 prefix)
        """
        if not lineage:
            return None

        node_idx = agent_indices.get(action_name)
        if node_idx is None:
            return None

        node_prefix = f"node_{node_idx}_"

        # Find the node_id that starts with the expected prefix
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
            node_idx: Node index of the action
            current_file_path: Current file being processed

        Returns:
            Path to the target file

        Example:
            action_name = "fact_extractor"
            node_idx = 0
            current_file_path = "target/node_2_cluster/file.json"

            Returns: Path("target/node_0_fact_extractor/file.json")
        """
        current_path = Path(current_file_path)
        file_name = current_path.name

        # Navigate to the target directory root
        # Assuming structure: target/node_X_action/file.json
        target_root = current_path.parent.parent

        # Construct the path to the historical node directory
        target_dir = target_root / f"node_{node_idx}_{action_name}"
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
    ) -> Optional[Dict]:
        """
        Find a record in the data that matches source_guid and optionally lineage.

        The matching strategy prioritizes source_guid as the primary identifier,
        with lineage-based matching providing disambiguation for split record scenarios.

        **Matching Logic**:
        1. Primary filter: source_guid (stable across granularity changes)
        2. Secondary filter: lineage prefix matching (for split records)

        **Scenarios Handled**:
        - Granularity changes (1 doc → N facts): Matches by source_guid
        - Split records (
            same source_guid,
            different branches): Uses lineage to select correct branch

        - Legacy workflows (no lineage): Returns first match by source_guid

        Args:
            data: List of records from the target file
            source_guid: Source GUID to match (required)
            node_id: Node ID (kept for logging/diagnostics, not used for matching)
            caller_lineage: Optional lineage from calling record for precise matching.
                          If None, uses legacy matching (source_guid only).
                          If provided, also checks lineage prefix matching.

        Returns:
            The matching record or None if not found

        Examples:
            # Legacy matching (backward compatible)
            >>> _find_record_by_identifiers(data, "guid-123", "node_5_abc")
            # Returns first record matching source_guid

            # Lineage-based matching (for split records)
            >>> caller_lineage = ["node_0", "node_1", "node_5", "node_6_a", "node_23"]
            >>> _find_record_by_identifiers(data, "guid-123", "node_5_abc", caller_lineage)
            # Returns only the record whose lineage is a prefix of caller_lineage
        """
        if not isinstance(data, list):
            logger.debug("[DEBUG _find_record] Data is not a list, type=%s", type(data))
            return None

        logger.debug(
            "[DEBUG _find_record] Searching %s records for source_guid=%s", len(data), source_guid
        )

        matches_found = 0
        first_source_guid_match = None  # Track first match as fallback

        for record in data:
            if not isinstance(record, dict):
                continue

            # Match by source_guid only (allows matching across granularity changes)
            # The node_id requirement was too strict and caused false negatives when
            # granularity changed (e.g., 1 document → 5 facts, each with different node_id)
            if record.get("source_guid") == source_guid:
                matches_found += 1
                caller_status = "provided" if caller_lineage else "None"
                logger.debug(
                    "[DEBUG _find_record] Match #%s: node_id=%s, has_lineage=%s, caller_lineage=%s",
                    matches_found,
                    record.get("node_id"),
                    bool(record.get("lineage")),
                    caller_status,
                )

                # Store first match as fallback for when lineage matching fails
                if first_source_guid_match is None:
                    first_source_guid_match = record

                # If caller_lineage is provided, use lineage matching for disambiguation
                # This is essential for split record scenarios where multiple records share
                # the same source_guid and node_id but differ in their processing branch
                if caller_lineage is not None:
                    record_lineage = record.get("lineage")
                    if HistoricalNodeDataLoader._lineages_match(record_lineage, caller_lineage):
                        return record
                    # Lineages don't match - continue searching for correct branch
                    continue

                # Legacy behavior: return first match when no lineage checking
                # This maintains backward compatibility for workflows without lineage
                logger.debug("[DEBUG _find_record] Returning match #%s", matches_found)
                return record

        # If we found source_guid matches but no lineage matches,
        # return first match as fallback
        if first_source_guid_match is not None:
            logger.debug(
                "[DEBUG _find_record] No lineage match found, "
                "returning first source_guid match as fallback"
            )
            return first_source_guid_match

        logger.debug(
            "[DEBUG _find_record] No matches found "
            "(searched %s records, found %s source_guid matches)",
            len(data),
            matches_found,
        )
        return None
