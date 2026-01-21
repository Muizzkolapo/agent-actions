"""
Passthrough Data Builder.
"""

from pathlib import Path
from typing import Dict, List, Optional, Any

from agent_actions.utilities.passthrough_item_builder import PassthroughItemBuilder
from agent_actions.llm_invocation.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm_invocation.batch.core.batch_constants import ContextMetaKeys


class BatchPassthroughBuilder:
    """
    Builder for creating passthrough data structures.

    Handles the creation of passthrough items for records that were filtered out
    or skipped during batch processing. Provides a single source of truth for
    passthrough item construction logic.

    Example:
        builder = BatchPassthroughBuilder(output_directory)

        # From raw data
        result = builder.from_data(
            data=[{'field': 'value', ...}],
            reason='conditional_clause_failed'
        )

        # From context map
        result = builder.from_context(
            context_map={'id1': {...}, 'id2': {...}},
            reason='where_clause_not_matched'
        )
    """

    def __init__(self, output_directory: Optional[str] = None):
        """
        Initialize passthrough builder.

        Args:
            output_directory: Path to output directory (e.g., '.../target/AgentName')
                            Used to extract action name for lineage tracking
        """
        self.output_directory = output_directory
        self.action_name = self._extract_action_name(output_directory)

    @staticmethod
    def _extract_action_name(output_directory: Optional[str]) -> str:
        """
        Extract action name from output directory path.

        Args:
            output_directory: Path like '.../target/AgentName'

        Returns:
            Action name extracted from the last path component
        """
        if not output_directory:
            return "unknown_action"
        return Path(output_directory).name

    def from_data(self, data: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
        """
        Build passthrough data from raw data list.

        Args:
            data: List of data items to convert to passthrough
            reason: Reason for passthrough (e.g., 'conditional_clause_failed')

        Returns:
            Dict with keys: type='passthrough', data=[...], output_directory
        """
        processed_data = []
        for row in data:
            item = self._build_item(row, reason)
            processed_data.append(item)

        return {
            "type": "passthrough",
            "data": processed_data,
            "output_directory": self.output_directory,
        }

    def from_context(self, context_map: Dict[str, Any], reason: str) -> Dict[str, Any]:
        """
        Build passthrough data from context map.

        Only processes items with _batch_filter_status='skipped'.
        Other items (included, filtered) are ignored.

        Args:
            context_map: Dictionary mapping custom_id -> row data
            reason: Reason for passthrough (e.g., 'where_clause_not_matched')

        Returns:
            Dict with keys: type='passthrough', data=[...], output_directory
        """
        processed_data = []
        for custom_id, original_row in context_map.items():
            if BatchContextMetadata.is_skipped(original_row):
                # Use custom_id as fallback for target_id
                item = self._build_item(original_row, reason, custom_id)
                # Remove internal tracking field
                item.pop(ContextMetaKeys.FILTER_STATUS, None)
                processed_data.append(item)

        return {
            "type": "passthrough",
            "data": processed_data,
            "output_directory": self.output_directory,
        }

    def _build_item(
        self, row: Dict[str, Any], reason: str, custom_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build a single passthrough item using unified PassthroughItemBuilder.

        This method now delegates to the unified PassthroughItemBuilder to eliminate
        code duplication with online mode.

        Args:
            row: Original data row
            reason: Reason for passthrough (stored in metadata)
            custom_id: Optional custom ID to use as fallback for target_id

        Returns:
            Passthrough item dict with target_id, source_guid, node_id, lineage, metadata
        """
        # Delegate to unified PassthroughItemBuilder
        return PassthroughItemBuilder.build_item(
            row=row,
            reason=reason,
            action_name=self.action_name,
            source_guid=row.get("source_guid"),
            custom_id=custom_id,
            mode="batch",
        )
