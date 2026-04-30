"""Unified passthrough item construction for batch and online modes."""

from typing import Any

from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.state import RecordState
from agent_actions.utils.field_management.manager import FieldManager
from agent_actions.utils.id_generation.generator import IDGenerator
from agent_actions.utils.lineage.builder import LineageBuilder


class PassthroughItemBuilder:
    """Unified builder for passthrough (tombstone) items across batch and online modes."""

    @staticmethod
    def build_item(
        row: dict[str, Any],
        reason: str,
        action_name: str,
        source_guid: str | None = None,
        custom_id: str | None = None,
        mode: str = "batch",
    ) -> dict[str, Any]:
        """Build a passthrough (tombstone) item with required fields and metadata.

        The returned item carries :attr:`RecordState.GUARD_SKIPPED` and
        ``_transitions`` — not ad-hoc skip flags on the record.

        Args:
            row: Original data item.
            reason: Passthrough reason (e.g., 'where_clause_not_matched').
            action_name: Action name for node ID generation.
            source_guid: Optional source GUID override.
            custom_id: Optional custom target_id (batch fallback).
            mode: 'batch' or 'online' (affects metadata format).

        Returns:
            Passthrough item dict.
        """
        target_id = row.get("target_id") or custom_id or IDGenerator.generate_target_id()
        resolved_source_guid = LineageBuilder.resolve_source_guid(
            source_guid, row, fallback=target_id
        )
        node_id = IDGenerator.generate_node_id(action_name)

        lineage = LineageBuilder.build_lineage(row, node_id)
        skipped_record = RecordEnvelope.build_skipped(action_name, row)
        content = skipped_record["content"]

        processed_item = FieldManager().create_processed_item(
            source_guid=resolved_source_guid,
            content=content,
            node_id=node_id,
            lineage=lineage,
            target_id=target_id,
        )

        LineageBuilder.set_parent_tracking(processed_item, row)

        processed_item["_state"] = RecordState.ACTIVE.value
        RecordEnvelope.transition(
            processed_item,
            RecordState.GUARD_SKIPPED,
            action_name=action_name,
            reason={"type": "passthrough", "reason": reason, "mode": mode},
        )

        return processed_item

    @staticmethod
    def _reason_to_legacy_flag(reason: str) -> str:
        """Map reason string to legacy batch-mode metadata flag name."""
        mapping = {
            "conditional_clause_failed": "skipped_by_conditional",
            "where_clause_not_matched": "skipped_by_where_clause",
        }
        return mapping.get(reason, "skipped_by_where_clause")
