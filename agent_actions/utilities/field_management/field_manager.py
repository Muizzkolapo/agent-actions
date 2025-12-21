"""
Field Management Service.

This module provides utilities for managing required fields in data objects:
- Ensure required fields exist (target_id, source_guid, node_id)
- Create processed items with all required fields
"""
from typing import Dict, Any, Optional, List
from agent_actions.utilities.id_generation import IDGenerator


class FieldManager:
    """Manages required fields in data objects."""

    def __init__(self, id_generator: Optional[IDGenerator] = None):
        """
        Initialize the field manager.

        Args:
            id_generator: Optional ID generator instance.
                         If not provided, uses IDGenerator class methods.
        """
        self.id_generator = id_generator or IDGenerator

    def ensure_required_fields(
        self,
        obj: Dict,
        source_guid: str,
        idx: int = 0
    ) -> Dict:
        """
        Ensure an object has all required fields.

        Required fields: target_id, source_guid, node_id.

        Args:
            obj: Object to update
            source_guid: Source GUID to use if missing
            idx: Index for node_id generation

        Returns:
            Updated object with all required fields
        """
        obj = obj.copy()
        if 'target_id' not in obj or not obj['target_id']:
            obj['target_id'] = self.id_generator.generate_target_id()
        if 'source_guid' not in obj or not obj['source_guid']:
            obj['source_guid'] = source_guid
        if 'node_id' not in obj or not obj['node_id']:
            obj['node_id'] = self.id_generator.generate_node_id(idx)
        return obj

    def create_processed_item(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        source_guid: str,
        content: Any,
        target_id: Optional[str] = None,
        node_id: Optional[str] = None,
        lineage: Optional[List[str]] = None
    ) -> Dict:
        """
        Create a standard processed item with all required fields.

        Args:
            source_guid: Source GUID for the item
            content: Content of the item
            target_id: Optional target ID (will generate if not provided)
            node_id: Optional node ID (will generate if not provided)
            lineage: Optional lineage (will create empty if not provided)

        Returns:
            Standard processed item dictionary
        """
        return {
            'source_guid': source_guid,
            'content': content,
            'target_id': target_id or self.id_generator.generate_target_id(),
            'node_id': node_id or self.id_generator.generate_node_id(0),
            'lineage': lineage or []
        }
