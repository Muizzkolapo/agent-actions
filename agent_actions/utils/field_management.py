"""Ensures required fields are present in data objects."""

from typing import Any

from agent_actions.utils.id_generation import IDGenerator


class FieldManager:
    """Manages required fields in data objects."""

    def __init__(self, id_generator: IDGenerator | None = None):
        """Initialize with an optional ID generator (defaults to IDGenerator)."""
        self.id_generator = id_generator or IDGenerator

    def ensure_required_fields(
        self,
        obj: dict,
        source_guid: str,
        action_name: str = "unknown_action",
        metadata: dict[str, Any] | None = None,
    ) -> dict:
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
        target_id: str | None = None,
        node_id: str | None = None,
        lineage: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        action_name: str = "unknown_action",
    ) -> dict:
        """Create a standard processed item with all required fields."""
        item: dict[str, Any] = {
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
        obj: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add metadata to *obj* in place and return it."""
        if metadata is not None:
            obj["metadata"] = metadata
        return obj
