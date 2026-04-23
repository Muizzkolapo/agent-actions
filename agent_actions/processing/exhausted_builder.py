"""Utilities for constructing exhausted retry records."""

from typing import Any

from agent_actions.processing.types import RecoveryMetadata
from agent_actions.utils.content import get_existing_content, wrap_content
from agent_actions.utils.id_generation import IDGenerator


class ExhaustedRecordBuilder:
    """Build exhausted records with empty content and recovery metadata."""

    @staticmethod
    def build_empty_content(agent_config: dict[str, Any]) -> dict[str, Any]:
        """Build empty content dict from action schema with type-appropriate defaults."""
        empty_content: dict[str, Any] = {}
        schema = agent_config.get("schema") if agent_config else None
        if schema and isinstance(schema, dict):
            for field_name, field_spec in schema.get("properties", {}).items():
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
                    empty_content[field_name] = ""
        return empty_content

    @staticmethod
    def build_exhausted_item(
        *,
        source_guid: str | None,
        original_row: dict[str, Any] | None,
        recovery_metadata: RecoveryMetadata,
        agent_config: dict[str, Any],
        action_name: str,
    ) -> dict[str, Any]:
        """Build an exhausted retry record with empty content and recovery metadata."""
        resolved_source_guid = source_guid
        if resolved_source_guid is None and isinstance(original_row, dict):
            resolved_source_guid = original_row.get("source_guid")
        if resolved_source_guid is None:
            resolved_source_guid = "unknown"

        empty_content = ExhaustedRecordBuilder.build_empty_content(agent_config)
        existing = get_existing_content(original_row) if isinstance(original_row, dict) else {}

        node_id = IDGenerator.generate_node_id(action_name)
        exhausted_item: dict[str, Any] = {
            "source_guid": resolved_source_guid,
            "content": wrap_content(action_name, empty_content, existing),
            "node_id": node_id,
            "metadata": {"retry_exhausted": True, "agent_type": "tombstone"},
            "_recovery": recovery_metadata.to_dict(),
            "_unprocessed": True,
        }

        if isinstance(original_row, dict):
            if original_row.get("target_id"):
                exhausted_item["target_id"] = original_row["target_id"]
                exhausted_item["parent_target_id"] = original_row["target_id"]
                if original_row.get("root_target_id"):
                    exhausted_item["root_target_id"] = original_row["root_target_id"]
                else:
                    exhausted_item["root_target_id"] = original_row["target_id"]
            if original_row.get("lineage"):
                exhausted_item["lineage"] = original_row["lineage"] + [node_id]
            else:
                exhausted_item["lineage"] = [node_id]
        else:
            exhausted_item["lineage"] = [node_id]

        return exhausted_item
