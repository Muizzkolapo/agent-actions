"""
Lineage Tracking Service.

This module provides utilities for building and tracking lineage chains:
- Filter valid node IDs from lineage
- Build lineage by appending node IDs
- Add lineage tracking to objects
"""
from typing import Dict, List, Any


class LineageBuilder:
    """Builds and tracks lineage chains for data processing."""

    @staticmethod
    def filter_node_lineage(lineage: List[Any]) -> List[str]:
        """
        Filter lineage to only include valid node IDs.

        Args:
            lineage: Raw lineage list

        Returns:
            Filtered list containing only valid node ID strings
        """
        if not isinstance(lineage, list):
            return []
        return [
            nid for nid in lineage
            if isinstance(nid, str) and nid.startswith('node_')
        ]

    @staticmethod
    def build_lineage(item: Dict, node_id: str) -> List[str]:
        """
        Build lineage by appending node_id to existing lineage.

        Args:
            item: Item containing potential lineage
            node_id: Node ID to append

        Returns:
            New lineage list
        """
        if 'lineage' in item and isinstance(item['lineage'], list):
            filtered_lineage = LineageBuilder.filter_node_lineage(
                item['lineage']
            )
            return filtered_lineage + [node_id]
        return [node_id]

    @staticmethod
    def add_lineage_tracking(
        obj: Dict,
        item: Dict,
        node_id: str
    ) -> Dict:
        """
        Add lineage tracking to an object based on source item.

        Args:
            obj: Object to add lineage to
            item: Source item containing lineage
            node_id: Node ID to append to lineage

        Returns:
            Object with lineage tracking added
        """
        obj = obj.copy()
        obj['node_id'] = node_id
        obj['lineage'] = LineageBuilder.build_lineage(item, node_id)
        return obj

    @staticmethod
    def add_context_lineage_tracking(
        obj: Dict,
        context_data: Any,
        node_id: str
    ) -> Dict:
        """
        Add lineage tracking to an object based on context data.

        Args:
            obj: Object to add lineage to
            context_data: Context data that may contain lineage
            node_id: Node ID to append to lineage

        Returns:
            Object with lineage tracking added
        """
        obj = obj.copy()
        obj['node_id'] = node_id
        if isinstance(context_data, dict) and 'lineage' in context_data:
            obj['lineage'] = context_data['lineage'] + [node_id]
        else:
            obj['lineage'] = [node_id]
        return obj

    @staticmethod
    def create_conditional_response(
        source_guid: str,
        content: Any,
        node_id: str,
        item: Dict = None
    ) -> Dict:
        """
        Create a standard response with lineage for conditional scenarios.

        Args:
            source_guid: Source GUID
            content: Original content to preserve
            node_id: Node ID for this item
            item: Optional source item for lineage tracking

        Returns:
            Processed item with lineage
        """
        lineage = (
            LineageBuilder.build_lineage(item, node_id)
            if item else [node_id]
        )
        return {
            'source_guid': source_guid,
            'content': content,
            'node_id': node_id,
            'lineage': lineage
        }
