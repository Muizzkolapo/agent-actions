"""
Lineage Tracking Service.
"""

import re
from typing import Dict, List, Any

# Pattern for valid node IDs: {action_name}_{identifier}
# action_name: valid Python identifier (starts with letter/underscore)
# identifier: any non-empty alphanumeric/dash sequence (UUID or simple ID)
# Examples: "extract_abc123", "node_2_a_0", "transform_a1b2c3d4-e5f6-7890"
_NODE_ID_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*_[a-zA-Z0-9_-]+$")


def _is_valid_node_id(value: str) -> bool:
    """
    Check if a string is a valid node ID.

    Valid node IDs have format: {action_name}_{identifier}
    where action_name is a valid identifier and the suffix is non-empty.

    Args:
        value: String to check

    Returns:
        True if valid node ID format
    """
    return bool(_NODE_ID_PATTERN.match(value))


class LineageBuilder:
    """Builds and tracks lineage chains for data processing."""

    @staticmethod
    def _propagate_ancestry_chain(obj: Dict, parent_item: Dict) -> None:
        """
        Propagate ancestry chain fields from parent to object.

        Sets parent_target_id to link to immediate parent's target_id.
        Sets root_target_id to preserve the original root ancestor.

        Args:
            obj: Object to update (modified in place)
            parent_item: Parent item containing ancestry fields
        """
        if "target_id" in parent_item:
            obj["parent_target_id"] = parent_item["target_id"]
        if "root_target_id" in parent_item:
            obj["root_target_id"] = parent_item["root_target_id"]
        elif "target_id" in parent_item:
            # If no root_target_id, parent is the root
            obj["root_target_id"] = parent_item["target_id"]

    @staticmethod
    def filter_node_lineage(lineage: List[Any]) -> List[str]:
        """
        Filter lineage to only include valid node IDs.

        Node IDs are in format: {action_name}_{uuid}

        Args:
            lineage: Raw lineage list

        Returns:
            Filtered list containing only valid node ID strings
        """
        if not isinstance(lineage, list):
            return []
        return [nid for nid in lineage if isinstance(nid, str) and _is_valid_node_id(nid)]

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
        LineageBuilder._propagate_ancestry_chain(obj, item)

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
            LineageBuilder._propagate_ancestry_chain(obj, context_data)
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
        LineageBuilder._propagate_ancestry_chain(obj, first_source)

        return obj

    @staticmethod
    def add_unified_lineage(obj: Dict, node_id: str, parent_item: Dict = None) -> Dict:
        """
        Unified lineage method for both first-stage and subsequent-stage.

        Replaces:
        - add_lineage_tracking() (subsequent-stage)
        - add_context_lineage_tracking() (first-stage)

        This method adds lineage tracking, node_id, and ancestry chain fields
        to an object based on an optional parent item.

        Args:
            obj: Object to add lineage to
            node_id: Node ID for this processing step
            parent_item: Optional parent item for lineage chain

        Returns:
            Object with lineage, node_id, and ancestry chain added
        """
        obj = obj.copy()
        obj["node_id"] = node_id

        # Build lineage chain
        if parent_item and "lineage" in parent_item:
            obj["lineage"] = LineageBuilder.build_lineage(parent_item, node_id)
        else:
            obj["lineage"] = [node_id]

        # Ancestry chain propagation
        if parent_item:
            LineageBuilder._propagate_ancestry_chain(obj, parent_item)

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
            LineageBuilder._propagate_ancestry_chain(response, item)

        return response
