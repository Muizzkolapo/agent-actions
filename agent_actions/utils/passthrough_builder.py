"""
Unified passthrough item construction for batch and online modes.

This module consolidates passthrough item building logic from batch
(batch_passthrough_builder.py) and online (record_processor.py) modes into a
unified interface.
"""

from typing import Dict, Optional, Any
from agent_actions.utils.field_management.field_manager import FieldManager
from agent_actions.utils.lineage.lineage_builder import LineageBuilder
from agent_actions.utils.id_generation.id_generator import IDGenerator


class PassthroughItemBuilder:
    """
    Unified builder for passthrough items across batch and online modes.

    This builder handles all passthrough item construction with consistent structure
    while supporting mode-specific metadata formats for backward compatibility.

    Note: Single static method is appropriate for builder utility pattern.
    """

    @staticmethod
    def build_item(
        row: Dict[str, Any],
        reason: str,
        action_name: str,
        source_guid: Optional[str] = None,
        custom_id: Optional[str] = None,
        mode: str = "batch",
    ) -> Dict[str, Any]:
        """
        Build passthrough item with consistent structure.

        This method creates a passthrough item with all required fields including
        target_id, source_guid, node_id, lineage, content, and metadata.

        Args:
            row: Original data item (must have 'content' key or entire dict
                is used as content)
            reason: Passthrough reason (e.g., 'where_clause_not_matched',
                'conditional_clause_failed')
            action_name: Action name for node ID generation
            source_guid: Optional source GUID (if not provided, uses
                row['source_guid'] or target_id)
            custom_id: Optional custom ID for target_id (batch mode fallback)
            mode: Processing mode - 'batch' or 'online' (affects metadata format)

        Returns:
            Passthrough item dict with structure:
            {
                'target_id': str,
                'source_guid': str,
                'node_id': str,
                'lineage': List[str],
                'content': Any,
                'metadata': {
                    'agent_type': 'passthrough',
                    'reason': str (online) or legacy flags (batch),
                    ...
                }
            }

        Example (batch mode):
            >>> row = {
            ...     'target_id': 'tgt_123',
            ...     'content': {'text': 'data'},
            ...     'lineage': ['extract_0']
            ... }
            >>> result = PassthroughItemBuilder.build_item(
            ...     row=row,
            ...     reason='where_clause_not_matched',
            ...     action_name='transform',
            ...     mode='batch'
            ... )
            >>> print(result['metadata'])
            {'agent_type': 'passthrough', 'skipped_by_where_clause': True}

        Example (online mode):
            >>> row = {
            ...     'source_guid': 'src_456',
            ...     'content': {'text': 'data'}
            ... }
            >>> result = PassthroughItemBuilder.build_item(
            ...     row=row,
            ...     reason='where_clause_not_matched',
            ...     action_name='transform',
            ...     source_guid='src_456',
            ...     mode='online'
            ... )
            >>> print(result['metadata'])
            {'agent_type': 'passthrough', 'reason': 'where_clause_not_matched',
             'skipped_by_where_clause': True}
        """
        # Generate IDs
        target_id = row.get("target_id") or custom_id or IDGenerator.generate_target_id()
        resolved_source_guid = source_guid or row.get("source_guid", target_id)
        node_id = IDGenerator.generate_node_id(action_name)

        # Build lineage (preserve existing lineage chain)
        lineage = LineageBuilder.build_lineage(row, node_id)

        # Extract content
        content = row.get("content", row)

        # Create base processed item using FieldManager
        processed_item = FieldManager().create_processed_item(
            source_guid=resolved_source_guid,
            content=content,
            node_id=node_id,
            lineage=lineage,
            target_id=target_id,
        )

        # Ensure metadata exists
        if "metadata" not in processed_item:
            processed_item["metadata"] = {}

        # Set agent_type to passthrough
        processed_item["metadata"]["agent_type"] = "passthrough"

        # Add mode-specific metadata
        if mode == "online":
            # Online mode: Use new reason-based metadata
            processed_item["metadata"]["reason"] = reason
            processed_item["metadata"]["skipped_by_where_clause"] = True
        else:  # batch
            # Batch mode: Use legacy flag-based metadata for backward compatibility
            flag_name = PassthroughItemBuilder._reason_to_legacy_flag(reason)
            processed_item["metadata"][flag_name] = True

        return processed_item

    @staticmethod
    def _reason_to_legacy_flag(reason: str) -> str:
        """
        Map reason string to legacy metadata flag name.

        This maintains backward compatibility with existing batch mode metadata format.

        Args:
            reason: Passthrough reason string

        Returns:
            Legacy flag name for metadata

        Mapping:
            - 'conditional_clause_failed' → 'skipped_by_conditional'
            - 'where_clause_not_matched' → 'skipped_by_where_clause'
            - Default → 'skipped_by_where_clause'

        Example:
            >>> PassthroughItemBuilder._reason_to_legacy_flag('conditional_clause_failed')
            'skipped_by_conditional'
            >>> PassthroughItemBuilder._reason_to_legacy_flag('where_clause_not_matched')
            'skipped_by_where_clause'
        """
        mapping = {
            "conditional_clause_failed": "skipped_by_conditional",
            "where_clause_not_matched": "skipped_by_where_clause",
        }
        return mapping.get(reason, "skipped_by_where_clause")
