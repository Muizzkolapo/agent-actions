"""Unified passthrough item construction for batch and online modes."""

from typing import Any

from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.state import RecordState
from agent_actions.utils.field_management import FieldManager
from agent_actions.utils.id_generation import IDGenerator
from agent_actions.utils.lineage import LineageBuilder


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
        state: RecordState = RecordState.GUARD_SKIPPED,
        cause: str | None = None,
    ) -> dict[str, Any]:
        """Build a passthrough (tombstone) item with required fields and metadata.

        The item carries ``metadata.agent_type = "tombstone"`` so downstream processing
        skips it. *state* is the state it is left in: a record that failed, or one an
        action above already failed, is not one the guard skipped, and what reads row
        state has to be able to tell. A guard skip carries a legacy ``skipped_by_*`` flag;
        any other state, and every online item, carries ``metadata.reason``. *cause* is
        what its history records, where the caller holds more than the reason, such as
        the error itself.
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

        if "metadata" not in processed_item:
            processed_item["metadata"] = {}

        if mode not in ("online", "batch"):
            raise ValueError(f"Invalid passthrough mode '{mode}' — must be 'online' or 'batch'")

        if mode == "online" or state is not RecordState.GUARD_SKIPPED:
            processed_item["metadata"]["reason"] = reason
        # The legacy flags all say "skipped by", which is true of a guard skip only.
        if state is RecordState.GUARD_SKIPPED:
            flag_name = PassthroughItemBuilder._reason_to_legacy_flag(reason)
            processed_item["metadata"][flag_name] = True

        processed_item["metadata"]["agent_type"] = "tombstone"
        processed_item["_tombstone"] = True
        processed_item["_tombstone_reason"] = reason

        RecordEnvelope.transition(processed_item, state, action_name, cause or reason)

        return processed_item

    @staticmethod
    def _reason_to_legacy_flag(reason: str) -> str:
        """Map reason string to legacy batch-mode metadata flag name."""
        mapping = {
            "conditional_clause_failed": "skipped_by_conditional",
            "where_clause_not_matched": "skipped_by_where_clause",
        }
        return mapping.get(reason, "skipped_by_where_clause")
