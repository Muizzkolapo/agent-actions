"""
Passthrough Data Builder.

Centralized logic for building passthrough data structures for filtered/skipped items.
Eliminates code duplication between different passthrough creation scenarios.

This builder now delegates to PassthroughItemBuilder for item construction,
providing a high-level interface for batch mode passthrough operations.
"""

import re
from typing import Dict, List, Optional, Any
from agent_actions.utilities.passthrough_item_builder import PassthroughItemBuilder
from agent_actions.llm_invocation.batch.batch_context_metadata import BatchContextMetadata
from agent_actions.llm_invocation.batch.batch_constants import ContextMetaKeys

# Import the constant from batch_service (or define here if needed)
NODE_DIRECTORY_PATTERN = r"node_(\d+)_(\w+)"


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
            output_directory: Path to output directory (e.g., '.../target/node_4_AgentName')
                            Used to extract node index for lineage tracking
        """
        self.output_directory = output_directory
        self.node_idx = self._extract_node_index(output_directory)

    @staticmethod
    def _extract_node_index(output_directory: Optional[str]) -> Optional[int]:
        """
        Extract node index from output directory path.

        Args:
            output_directory: Path like '.../target/node_4_AgentName'

        Returns:
            Node index (e.g., 4) or None if pattern doesn't match
        """
        if not output_directory:
            return None
        match = re.search(NODE_DIRECTORY_PATTERN, str(output_directory))
        return int(match.group(1)) if match else None

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
            idx=self.node_idx if self.node_idx is not None else 0,
            source_guid=row.get("source_guid"),
            custom_id=custom_id,
            mode="batch",
        )
