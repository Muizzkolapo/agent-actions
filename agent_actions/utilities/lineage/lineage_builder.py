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
        return [nid for nid in lineage if isinstance(nid, str) and nid.startswith("node_")]

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
        if "lineage" in item and isinstance(item["lineage"], list):
            filtered_lineage = LineageBuilder.filter_node_lineage(item["lineage"])
            return filtered_lineage + [node_id]
        return [node_id]

    @staticmethod
    def add_lineage_tracking(obj: Dict, item: Dict, node_id: str) -> Dict:
        """
        Add lineage tracking to an object based on source item.

        Also propagates Ancestry Chain fields:
        - parent_target_id: Links to input item's target_id
        - root_target_id: Preserves the original root from input

        Args:
            obj: Object to add lineage to
            item: Source item containing lineage
            node_id: Node ID to append to lineage

        Returns:
            Object with lineage tracking added
        """
        obj = obj.copy()
        obj["node_id"] = node_id
        obj["lineage"] = LineageBuilder.build_lineage(item, node_id)

        # Ancestry Chain propagation (RFC: docs/specs/RFC_ancestry_chain.md)
        # parent_target_id = input's target_id (link to immediate parent)
        # root_target_id = input's root_target_id (preserve original ancestor)
        if "target_id" in item:
            obj["parent_target_id"] = item["target_id"]
        if "root_target_id" in item:
            obj["root_target_id"] = item["root_target_id"]
        elif "target_id" in item:
            # If no root_target_id, input is the root
            obj["root_target_id"] = item["target_id"]

        return obj

    @staticmethod
    def add_context_lineage_tracking(obj: Dict, context_data: Any, node_id: str) -> Dict:
        """
        Add lineage tracking to an object based on context data.

        Also propagates Ancestry Chain fields from context_data.

        Args:
            obj: Object to add lineage to
            context_data: Context data that may contain lineage
            node_id: Node ID to append to lineage

        Returns:
            Object with lineage tracking added
        """
        obj = obj.copy()
        obj["node_id"] = node_id
        if isinstance(context_data, dict) and "lineage" in context_data:
            obj["lineage"] = context_data["lineage"] + [node_id]

            # Ancestry Chain propagation
            if "target_id" in context_data:
                obj["parent_target_id"] = context_data["target_id"]
            if "root_target_id" in context_data:
                obj["root_target_id"] = context_data["root_target_id"]
            elif "target_id" in context_data:
                obj["root_target_id"] = context_data["target_id"]
        else:
            obj["lineage"] = [node_id]
        return obj

    @staticmethod
    def add_lineage_tracking_from_sources(
        obj: Dict, source_items: List[Dict], node_id: str
    ) -> Dict:
        """
        Add lineage from multiple source items (many-to-one).

        For single source: standard lineage chain
        For multiple sources: uses first source's lineage chain and adds
        lineage_sources field with all parent node_ids for full traceability.

        Also propagates Ancestry Chain fields from the first source item.

        Args:
            obj: Object to add lineage to
            source_items: List of source items that contributed to this output
            node_id: Node ID for this output

        Returns:
            Object with lineage tracking:
            - Single source: {lineage: [..., node_id], node_id: ...}
            - Multiple sources: {lineage: [..., node_id], node_id: ..., lineage_sources: [...]}
        """
        obj = obj.copy()
        obj["node_id"] = node_id

        if not source_items:
            obj["lineage"] = [node_id]
            return obj

        # Use first source for ancestry chain
        first_source = source_items[0]

        if len(source_items) == 1:
            # Single source: standard lineage
            obj["lineage"] = LineageBuilder.build_lineage(first_source, node_id)
        else:
            # Multiple sources: collect parent node_ids from each
            parent_node_ids = []
            for item in source_items:
                lineage = item.get("lineage", [])
                filtered = LineageBuilder.filter_node_lineage(lineage)
                if filtered:
                    # Get the last node_id (immediate parent)
                    parent_node_ids.append(filtered[-1])

            # Use first source's lineage as the primary chain
            base_lineage = LineageBuilder.filter_node_lineage(first_source.get("lineage", []))
            obj["lineage"] = base_lineage + [node_id]

            # Add lineage_sources for full traceability of merged records
            if parent_node_ids:
                obj["lineage_sources"] = parent_node_ids

        # Ancestry Chain propagation from first source
        if "target_id" in first_source:
            obj["parent_target_id"] = first_source["target_id"]
        if "root_target_id" in first_source:
            obj["root_target_id"] = first_source["root_target_id"]
        elif "target_id" in first_source:
            obj["root_target_id"] = first_source["target_id"]

        return obj

    @staticmethod
    def create_conditional_response(
        source_guid: str, content: Any, node_id: str, item: Dict = None
    ) -> Dict:
        """
        Create a standard response with lineage for conditional scenarios.

        Also propagates Ancestry Chain fields from the source item.

        Args:
            source_guid: Source GUID
            content: Original content to preserve
            node_id: Node ID for this item
            item: Optional source item for lineage tracking

        Returns:
            Processed item with lineage and ancestry
        """
        lineage = LineageBuilder.build_lineage(item, node_id) if item else [node_id]
        response = {
            "source_guid": source_guid,
            "content": content,
            "node_id": node_id,
            "lineage": lineage,
        }

        # Ancestry Chain propagation
        if item:
            if "target_id" in item:
                response["parent_target_id"] = item["target_id"]
            if "root_target_id" in item:
                response["root_target_id"] = item["root_target_id"]
            elif "target_id" in item:
                response["root_target_id"] = item["target_id"]

        return response
