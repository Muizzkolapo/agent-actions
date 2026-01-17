"""Utilities for constructing exhausted retry records."""

from typing import Any, Dict, Optional

from agent_actions.core.types import RecoveryMetadata
from agent_actions.utilities.id_generation import IDGenerator


class ExhaustedRecordBuilder:
    """Build exhausted records with empty content and recovery metadata."""

    @staticmethod
    def build_exhausted_item(
        *,
        source_guid: Optional[str],
        original_row: Any,
        recovery_metadata: RecoveryMetadata,
        agent_config: Dict[str, Any],
        action_name: str,
    ) -> Dict[str, Any]:
        """
        Build an exhausted retry record.

        Args:
            source_guid: Source GUID for the record.
            original_row: Original input row (for lineage and target_id).
            recovery_metadata: Recovery metadata containing retry info.
            agent_config: Agent configuration for schema hints.
            action_name: Action name for node ID generation.

        Returns:
            Exhausted record dict.
        """
        resolved_source_guid = source_guid
        if resolved_source_guid is None and isinstance(original_row, dict):
            resolved_source_guid = original_row.get("source_guid")
        if resolved_source_guid is None:
            resolved_source_guid = "unknown"

        empty_content: Dict[str, Any] = {}
        schema = agent_config.get("schema") if agent_config else None
        if schema and isinstance(schema, dict):
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

        node_id = IDGenerator.generate_node_id(action_name)
        exhausted_item: Dict[str, Any] = {
            "source_guid": resolved_source_guid,
            "content": empty_content,
            "node_id": node_id,
            "metadata": {"retry_exhausted": True},
            "_recovery": recovery_metadata.to_dict(),
        }

        if isinstance(original_row, dict):
            if original_row.get("target_id"):
                exhausted_item["target_id"] = original_row["target_id"]
            if original_row.get("parent_target_id"):
                exhausted_item["parent_target_id"] = original_row["parent_target_id"]
            if original_row.get("root_target_id"):
                exhausted_item["root_target_id"] = original_row["root_target_id"]
            if original_row.get("lineage"):
                exhausted_item["lineage"] = original_row["lineage"] + [node_id]
            else:
                exhausted_item["lineage"] = [node_id]
        else:
            exhausted_item["lineage"] = [node_id]

        return exhausted_item
