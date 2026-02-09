"""Passthrough Data Builder."""

from pathlib import Path
from typing import Dict, List, Optional, Any

from agent_actions.utils.passthrough_builder import PassthroughItemBuilder
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys


class BatchPassthroughBuilder:
    """Builder for creating passthrough data structures."""

    def __init__(self, output_directory: Optional[str] = None):
        self.output_directory = output_directory
        self.action_name = self._extract_action_name(output_directory)

    @staticmethod
    def _extract_action_name(output_directory: Optional[str]) -> str:
        if not output_directory:
            return "unknown_action"
        return Path(output_directory).name

    def from_data(self, data: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
        processed_data = []
        for row in data:
            item = self._build_item(row, reason)
            processed_data.append(item)

        return {
            "type": "tombstone",
            "data": processed_data,
            "output_directory": self.output_directory,
        }

    def from_context(self, context_map: Dict[str, Any], reason: str) -> Dict[str, Any]:
        processed_data = []
        for custom_id, original_row in context_map.items():
            if BatchContextMetadata.is_skipped(original_row):
                item = self._build_item(original_row, reason, custom_id)
                item.pop(ContextMetaKeys.FILTER_STATUS, None)
                processed_data.append(item)

        return {
            "type": "tombstone",
            "data": processed_data,
            "output_directory": self.output_directory,
        }

    def _build_item(
        self, row: Dict[str, Any], reason: str, custom_id: Optional[str] = None
    ) -> Dict[str, Any]:
        return PassthroughItemBuilder.build_item(
            row=row,
            reason=reason,
            action_name=self.action_name,
            source_guid=row.get("source_guid"),
            custom_id=custom_id,
            mode="batch",
        )
