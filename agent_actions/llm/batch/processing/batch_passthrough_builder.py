"""Passthrough Data Builder."""

from typing import Any

from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys, FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.record.reasons import PREP_FAILED
from agent_actions.record.state import RecordState
from agent_actions.utils.passthrough_builder import PassthroughItemBuilder


class BatchPassthroughBuilder:
    """Builder for creating passthrough data structures."""

    def __init__(self, output_directory: str | None = None, action_name: str = "unknown_action"):
        self.output_directory = output_directory
        self.action_name = action_name

    def from_data(self, data: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        processed_data = []
        for row in data:
            item = self._build_item(row, reason)
            processed_data.append(item)

        return {
            "type": "tombstone",
            "data": processed_data,
            "output_directory": self.output_directory,
        }

    def from_context(self, context_map: dict[str, Any], reason: str) -> dict[str, Any]:
        processed_data = []
        for custom_id, original_row in context_map.items():
            status = BatchContextMetadata.get_filter_status(original_row)
            if status == FilterStatus.FAILED:
                item = self._build_item(original_row, PREP_FAILED, custom_id, RecordState.FAILED)
            elif status == FilterStatus.SKIPPED:
                item = self._build_item(original_row, reason, custom_id)
            else:
                continue
            item.pop(ContextMetaKeys.FILTER_STATUS, None)
            processed_data.append(item)

        return {
            "type": "tombstone",
            "data": processed_data,
            "output_directory": self.output_directory,
        }

    def _build_item(
        self,
        row: dict[str, Any],
        reason: str,
        custom_id: str | None = None,
        state: RecordState = RecordState.GUARD_SKIPPED,
    ) -> dict[str, Any]:
        return PassthroughItemBuilder.build_item(
            row=row,
            reason=reason,
            action_name=self.action_name,
            source_guid=row.get("source_guid"),
            custom_id=custom_id,
            mode="batch",
            state=state,
        )
