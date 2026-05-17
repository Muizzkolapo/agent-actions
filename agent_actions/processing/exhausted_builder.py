"""Utilities for constructing exhausted retry records."""

from typing import Any

from agent_actions.processing.types import RecoveryMetadata
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.reasons import RETRY_EXHAUSTED
from agent_actions.utils.id_generation import IDGenerator
from agent_actions.utils.lineage.builder import LineageBuilder


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
        """Build an exhausted retry record with empty content and recovery metadata.

        Routes through :meth:`RecordEnvelope.build` so lifecycle fields
        (``_state_history``, ``_state_schema_version``) are carried automatically.
        """
        resolved_source_guid = LineageBuilder.resolve_source_guid(source_guid, original_row)
        empty_content = ExhaustedRecordBuilder.build_empty_content(agent_config)

        exhausted_item = RecordEnvelope.build(
            action_name, empty_content, original_row if isinstance(original_row, dict) else None
        )

        exhausted_item["source_guid"] = resolved_source_guid
        node_id = IDGenerator.generate_node_id(action_name)
        exhausted_item["node_id"] = node_id
        exhausted_item["metadata"] = {"retry_exhausted": True, "agent_type": "tombstone"}
        exhausted_item["_tombstone"] = True
        exhausted_item["_tombstone_reason"] = RETRY_EXHAUSTED
        exhausted_item["_recovery"] = recovery_metadata.to_dict()

        if isinstance(original_row, dict):
            if "target_id" in original_row and original_row["target_id"]:
                exhausted_item["target_id"] = original_row["target_id"]
            exhausted_item["lineage"] = LineageBuilder.build_lineage(original_row, node_id)
            LineageBuilder.set_parent_tracking(exhausted_item, original_row)
        else:
            exhausted_item["lineage"] = [node_id]

        return exhausted_item
