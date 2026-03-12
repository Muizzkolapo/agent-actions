"""Ensures required fields are present in data objects."""

from typing import Dict, Any, Optional, List
from agent_actions.utils.id_generation import IDGenerator


class FieldManager:
    """Manages required fields in data objects."""

    def __init__(self, id_generator: Optional[IDGenerator] = None):
        """Initialize with an optional ID generator (defaults to IDGenerator)."""
        self.id_generator = id_generator or IDGenerator

    def ensure_required_fields(
        self,
        obj: Dict,
        source_guid: str,
        action_name: str = "unknown_action",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """Ensure an object has target_id, source_guid, node_id, and optional metadata."""
        obj = obj.copy()
        if "target_id" not in obj or not obj["target_id"]:
            obj["target_id"] = self.id_generator.generate_target_id()
        if "source_guid" not in obj or not obj["source_guid"]:
            obj["source_guid"] = source_guid
        if "node_id" not in obj or not obj["node_id"]:
            obj["node_id"] = self.id_generator.generate_node_id(action_name)

        if metadata is not None and "metadata" not in obj:
            obj["metadata"] = metadata

        return obj

    def create_processed_item(
        self,
        source_guid: str,
        content: Any,
        target_id: Optional[str] = None,
        node_id: Optional[str] = None,
        lineage: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        action_name: str = "unknown_action",
    ) -> Dict:
        """Create a standard processed item with all required fields."""
        item: Dict[str, Any] = {
            "source_guid": source_guid,
            "content": content,
            "target_id": target_id or self.id_generator.generate_target_id(),
            "node_id": node_id or self.id_generator.generate_node_id(action_name),
            "lineage": lineage or [],
        }

        if metadata is not None:
            item["metadata"] = metadata

        return item

    @staticmethod
    def add_metadata(
        obj: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Add metadata to *obj* in place and return it."""
        if metadata is not None:
            obj["metadata"] = metadata
        return obj
