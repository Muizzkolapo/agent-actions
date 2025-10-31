"""Module for loading historical node data from target files using lineage tracking."""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from agent_actions.cli.utils.service_logger import ServiceLogger

logger = logging.getLogger(__name__)


class HistoricalNodeDataLoader:
    """
    Loads historical node data from target directories using lineage tracking.

    This class enables referencing upstream agent outputs using {action_name.field}
    syntax by finding and loading the appropriate target file based on lineage.
    """

    @staticmethod
    def load_historical_node_data(
        action_name: str,
        lineage: List[str],
        source_guid: str,
        file_path: str,
        agent_indices: Dict[str, int]
    ) -> Optional[Dict[str, Any]]:
        """
        Load historical node data for a specific action from target files.

        Args:
            action_name: Name of the agent/action to load data from (e.g., 'fact_extractor')
            lineage: List of node_ids tracking the record's lineage
            source_guid: Source GUID to match the record
            file_path: Current file path being processed
            agent_indices: Mapping of agent names to their node indices

        Returns:
            Content dict from the historical node, or None if not found

        Example:
            lineage = ["node_0_abc123", "node_1_def456"]
            action_name = "fact_extractor"
            agent_indices = {"fact_extractor": 0, "flatten_facts": 1}

            Returns content from target/node_0_fact_extractor/file.json
            where record matches source_guid and node_id="node_0_abc123"
        """
        try:
            ServiceLogger.log_operation_start(
                logger, "load historical node data",
                action_name=action_name,
                source_guid=source_guid
            )

            # Find the node_id in lineage that corresponds to this action
            node_id = HistoricalNodeDataLoader._find_node_in_lineage(
                action_name, lineage, agent_indices
            )

            if not node_id:
                logger.warning(
                    f"No node_id found in lineage for action '{action_name}'. "
                    f"Lineage: {lineage}"
                )
                return None

            # Get the node index for constructing the path
            node_idx = agent_indices.get(action_name)
            if node_idx is None:
                logger.warning(f"No index found for action '{action_name}' in agent_indices")
                return None

            # Construct path to the target file
            target_path = HistoricalNodeDataLoader._construct_target_path(
                action_name, node_idx, file_path
            )

            if not target_path.exists():
                logger.warning(f"Target file does not exist: {target_path}")
                return None

            # Load and find the record
            with open(target_path, 'r') as f:
                data = json.load(f)

            record = HistoricalNodeDataLoader._find_record_by_identifiers(
                data, source_guid, node_id
            )

            if record:
                ServiceLogger.log_operation_success(
                    logger, "load historical node data",
                    action_name=action_name,
                    node_id=node_id
                )
                return record.get('content')
            else:
                logger.warning(
                    f"No record found for source_guid={source_guid}, "
                    f"node_id={node_id} in {target_path}"
                )
                return None

        except Exception as e:
            ServiceLogger.log_operation_error(logger, "load historical node data", e)
            # Don't raise - return None to allow processing to continue
            return None

    @staticmethod
    def _find_node_in_lineage(
        action_name: str,
        lineage: List[str],
        agent_indices: Dict[str, int]
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
    def _construct_target_path(
        action_name: str,
        node_idx: int,
        current_file_path: str
    ) -> Path:
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
    def _find_record_by_identifiers(
        data: List[Dict],
        source_guid: str,
        node_id: str
    ) -> Optional[Dict]:
        """
        Find a record in the data that matches both source_guid and node_id.

        Args:
            data: List of records from the target file
            source_guid: Source GUID to match
            node_id: Node ID to match

        Returns:
            The matching record or None if not found
        """
        if not isinstance(data, list):
            return None

        for record in data:
            if not isinstance(record, dict):
                continue

            # Match by both source_guid and node_id for precise identification
            if (record.get('source_guid') == source_guid and
                record.get('node_id') == node_id):
                return record

        return None
