"""Shared utility for creating exhausted retry records."""

from typing import Any, Dict, Optional
import logging

from agent_actions.core.types import RecoveryMetadata
from agent_actions.utilities.id_generation import IDGenerator

logger = logging.getLogger(__name__)


class ExhaustedRecordBuilder:
    """
    Build exhausted retry items when retry attempts are exhausted.

    Provides unified interface for both batch and online modes to create
    records with empty schema fields when retries are exhausted.
    """

    @staticmethod
    def build_exhausted_item(
        source_guid: str,
        original_row: Optional[Dict[str, Any]],
        recovery_metadata: RecoveryMetadata,
        agent_config: Dict[str, Any],
        action_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build an exhausted retry item with empty schema fields.

        Args:
            source_guid: Source GUID for lineage tracking
            original_row: Original row data (for target_id, lineage preservation)
            recovery_metadata: Recovery metadata with retry info
            agent_config: Agent configuration (for schema, agent_type)
            action_name: Override action name (defaults to agent_type from config)

        Returns:
            Exhausted item dict with empty content + _recovery metadata
        """
        # Build empty content based on schema
        empty_content: Dict[str, Any] = {}
        schema = agent_config.get("schema", {})
        if isinstance(schema, dict):
            properties = schema.get("properties", {})
            for field_name, field_spec in properties.items():
                field_type = field_spec.get("type", "string")
                if field_type == "array":
                    empty_content[field_name] = []
                elif field_type == "object":
                    empty_content[field_name] = {}
                elif field_type == "boolean":
                    empty_content[field_name] = False
                elif field_type in ("number", "integer"):
                    empty_content[field_name] = 0
                else:
                    empty_content[field_name] = None

        # Generate node_id
        if not action_name:
            action_name = agent_config.get("agent_type", agent_config.get("name", "unknown_action"))
        node_id = IDGenerator.generate_node_id(action_name)

        # Build exhausted record
        exhausted_item: Dict[str, Any] = {
            "source_guid": source_guid,
            "content": empty_content,
            "node_id": node_id,
            "metadata": {"retry_exhausted": True},
            "_recovery": recovery_metadata.to_dict(),
        }

        # Preserve lineage from original row
        if original_row:
            if original_row.get("target_id"):
                exhausted_item["target_id"] = original_row["target_id"]
            if original_row.get("lineage"):
                exhausted_item["lineage"] = original_row["lineage"] + [node_id]
            else:
                exhausted_item["lineage"] = [node_id]
        else:
            exhausted_item["lineage"] = [node_id]

        return exhausted_item
