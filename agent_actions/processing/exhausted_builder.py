"""Utilities for constructing exhausted retry records."""

from typing import Any

from agent_actions.processing.types import RecoveryMetadata
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.state import RecordState, reason_exhausted
from agent_actions.utils.content import get_existing_content
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
        """Build an exhausted retry record with empty content and recovery metadata."""
        resolved_source_guid = LineageBuilder.resolve_source_guid(source_guid, original_row)

        empty_content = ExhaustedRecordBuilder.build_empty_content(agent_config)
        existing = get_existing_content(original_row) if isinstance(original_row, dict) else {}

        node_id = IDGenerator.generate_node_id(action_name)
        exhausted_item: dict[str, Any] = {
            "source_guid": resolved_source_guid,
            "content": RecordEnvelope.build_content(action_name, empty_content, existing),
            "node_id": node_id,
            "metadata": {"retry_exhausted": True},
            "_recovery": recovery_metadata.to_dict(),
            "_state": RecordState.ACTIVE.value,
        }

        RecordEnvelope.transition(
            exhausted_item,
            RecordState.EXHAUSTED,
            action_name=action_name,
            reason=reason_exhausted(
                attempts=recovery_metadata.retry.attempts if recovery_metadata.retry else "unknown",
                last_error=recovery_metadata.retry.reason if recovery_metadata.retry else None,
                model=None,
            ),
        )

        if isinstance(original_row, dict):
            if "target_id" in original_row and original_row["target_id"]:
                exhausted_item["target_id"] = original_row["target_id"]
            exhausted_item["lineage"] = LineageBuilder.build_lineage(original_row, node_id)
            LineageBuilder.set_parent_tracking(exhausted_item, original_row)
        else:
            exhausted_item["lineage"] = [node_id]

        return exhausted_item
