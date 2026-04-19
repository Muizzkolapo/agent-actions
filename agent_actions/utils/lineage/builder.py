"""Lineage chain construction and ancestry tracking for data processing."""

import re
from typing import Any

# Pattern for valid node IDs: {action_name}_{identifier}
# action_name: valid Python identifier (starts with letter/underscore)
# identifier: any non-empty alphanumeric/dash sequence (UUID or simple ID)
# Examples: "extract_abc123", "node_2_a_0", "transform_a1b2c3d4-e5f6-7890"
_NODE_ID_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*_[a-zA-Z0-9_-]+$")


def _is_valid_node_id(value: str) -> bool:
    """Check if *value* matches the ``{action_name}_{identifier}`` node ID format."""
    return bool(_NODE_ID_PATTERN.match(value))


class LineageBuilder:
    """Builds and tracks lineage chains for data processing."""

    @staticmethod
    def _propagate_ancestry_chain(obj: dict, parent_item: dict) -> None:
        """Propagate parent_target_id, root_target_id, and source_guid from parent to *obj* in place."""
        if "target_id" in parent_item:
            obj["parent_target_id"] = parent_item["target_id"]
        if "root_target_id" in parent_item:
            obj["root_target_id"] = parent_item["root_target_id"]
        elif "target_id" in parent_item:
            obj["root_target_id"] = parent_item["target_id"]
        # Propagate source_guid from parent when not already set on obj.
        # source_guid tracks which original input record this data descends from;
        # it is a framework concept that must survive FILE-mode tool transformations.
        if ("source_guid" not in obj or not obj["source_guid"]) and parent_item.get("source_guid"):
            obj["source_guid"] = parent_item["source_guid"]
        # Propagate lineage_sources so Mode 2 historical lookup resolves all parallel branches.
        if "lineage_sources" in parent_item and "lineage_sources" not in obj:
            obj["lineage_sources"] = parent_item["lineage_sources"].copy()

    @staticmethod
    def filter_node_lineage(lineage: list[Any]) -> list[str]:
        """Filter lineage to only include valid node IDs."""
        if not isinstance(lineage, list):
            return []  # type: ignore[unreachable]
        return [nid for nid in lineage if isinstance(nid, str) and _is_valid_node_id(nid)]

    @staticmethod
    def build_lineage(item: dict, node_id: str) -> list[str]:
        """Build lineage by appending *node_id* to the item's existing lineage."""
        if "lineage" in item and isinstance(item["lineage"], list):
            filtered_lineage = LineageBuilder.filter_node_lineage(item["lineage"])
            return filtered_lineage + [node_id]
        return [node_id]

    @staticmethod
    def add_lineage_tracking(obj: dict, item: dict, node_id: str) -> dict:
        """Add lineage and ancestry chain fields to *obj* based on source *item*."""
        obj = obj.copy()
        obj["node_id"] = node_id
        obj["lineage"] = LineageBuilder.build_lineage(item, node_id)

        # Ancestry Chain propagation (RFC: docs/specs/RFC_ancestry_chain.md)
        LineageBuilder._propagate_ancestry_chain(obj, item)

        return obj

    @staticmethod
    def add_lineage_tracking_from_sources(
        obj: dict, source_items: list[dict], node_id: str
    ) -> dict:
        """Add lineage from multiple source items (many-to-one).

        For multiple sources, adds a ``lineage_sources`` field with all parent
        node_ids. Ancestry chain is propagated from the first source item.
        """
        obj = obj.copy()
        obj["node_id"] = node_id

        if not source_items:
            obj["lineage"] = [node_id]
            return obj

        first_source = source_items[0]

        if len(source_items) == 1:
            obj["lineage"] = LineageBuilder.build_lineage(first_source, node_id)
        else:
            parent_node_ids = []
            for item in source_items:
                lineage = item.get("lineage", [])
                filtered = LineageBuilder.filter_node_lineage(lineage)
                if filtered:
                    parent_node_ids.append(filtered[-1])

            base_lineage = LineageBuilder.filter_node_lineage(first_source.get("lineage", []))
            obj["lineage"] = base_lineage + [node_id]

            if parent_node_ids:
                obj["lineage_sources"] = parent_node_ids

        LineageBuilder._propagate_ancestry_chain(obj, first_source)

        return obj

    @staticmethod
    def add_unified_lineage(obj: dict, node_id: str, parent_item: dict | None = None) -> dict:
        """Add lineage, node_id, and ancestry chain to *obj* from an optional parent."""
        obj = obj.copy()
        obj["node_id"] = node_id

        if parent_item and "lineage" in parent_item:
            obj["lineage"] = LineageBuilder.build_lineage(parent_item, node_id)
        else:
            obj["lineage"] = [node_id]

        if parent_item:
            LineageBuilder._propagate_ancestry_chain(obj, parent_item)

        return obj

    @staticmethod
    def create_conditional_response(
        source_guid: str, content: Any, node_id: str, item: dict | None = None
    ) -> dict:
        """Create a standard response with lineage and ancestry for conditional scenarios."""
        lineage = LineageBuilder.build_lineage(item, node_id) if item else [node_id]
        response = {
            "source_guid": source_guid,
            "content": content,
            "node_id": node_id,
            "lineage": lineage,
        }

        if item:
            LineageBuilder._propagate_ancestry_chain(response, item)

        return response
