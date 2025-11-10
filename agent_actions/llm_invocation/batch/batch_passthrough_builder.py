"""
Passthrough Data Builder.

Centralized logic for building passthrough data structures for filtered/skipped items.
Eliminates code duplication between different passthrough creation scenarios.
"""

import re
from typing import Dict, List, Optional, Any
from agent_actions.utilities.id_generation import IDGenerator
from agent_actions.utilities.field_management import FieldManager
from agent_actions.utilities.lineage import LineageBuilder
from agent_actions.utilities.correlation import LoopCorrelator

# Import the constant from batch_service (or define here if needed)
NODE_DIRECTORY_PATTERN = r'node_(\d+)_(\w+)'


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
            'type': 'passthrough',
            'data': processed_data,
            'output_directory': self.output_directory
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
            filter_status = original_row.get('_batch_filter_status', 'included')
            if filter_status == 'skipped':
                # Use custom_id as fallback for target_id
                item = self._build_item(original_row, reason, custom_id)
                # Remove internal tracking field
                item.pop('_batch_filter_status', None)
                processed_data.append(item)

        return {
            'type': 'passthrough',
            'data': processed_data,
            'output_directory': self.output_directory
        }

    def _build_item(self, row: Dict[str, Any], reason: str,
                    custom_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Build a single passthrough item with proper metadata.

        This is the single source of truth for passthrough item construction.
        All passthrough creation logic flows through this method.

        Args:
            row: Original data row
            reason: Reason for passthrough (stored in metadata)
            custom_id: Optional custom ID to use as fallback for target_id

        Returns:
            Passthrough item dict with target_id, source_guid, node_id, lineage, metadata
        """
        # 1. Determine target_id (generate if missing)
        target_id = row.get('target_id')
        if not target_id:
            target_id = custom_id or IDGenerator.generate_target_id()
            row['target_id'] = target_id

        # 2. Determine source_guid (defaults to target_id)
        original_source_guid = row.get('source_guid', target_id)

        # 3. Create passthrough item (copy of original)
        passthrough_item = row.copy()

        # 4. Ensure required fields are set
        if 'target_id' not in passthrough_item or not passthrough_item['target_id']:
            passthrough_item['target_id'] = target_id
        if 'source_guid' not in passthrough_item or not passthrough_item['source_guid']:
            passthrough_item['source_guid'] = original_source_guid

        # 5. Add node tracking if node_idx is available
        if self.node_idx is not None:
            item_node_id = IDGenerator.generate_node_id(self.node_idx)
            passthrough_item['node_id'] = item_node_id
            passthrough_item['lineage'] = LineageBuilder.build_lineage(row, item_node_id)

        # 6. Add metadata with passthrough reason
        # Determine the legacy flag based on reason for backward compatibility
        legacy_flag = self._get_legacy_flag(reason)
        passthrough_item['metadata'] = {
            legacy_flag: True,  # For backward compatibility
            'agent_type': 'passthrough'
            # Note: 'reason' field omitted to match legacy behavior
        }

        return passthrough_item

    @staticmethod
    def _get_legacy_flag(reason: str) -> str:
        """
        Map reason to legacy metadata flag for backward compatibility.

        Args:
            reason: Passthrough reason string

        Returns:
            Legacy flag name (e.g., 'skipped_by_conditional')
        """
        # Map common reasons to their legacy flag names
        reason_to_flag = {
            'conditional_clause_failed': 'skipped_by_conditional',
            'where_clause_not_matched': 'skipped_by_where_clause',
        }
        return reason_to_flag.get(reason, 'skipped_by_conditional')
