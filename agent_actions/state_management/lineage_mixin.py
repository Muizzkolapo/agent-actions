"""
Lineage tracking mixin for processors.

This module provides a mixin class that standardizes lineage tracking
operations across different processor implementations.
"""

import logging
from typing import Dict, List, Any, Optional

from agent_actions.utilities.id_generation import IDGenerator
from agent_actions.utilities.field_management import FieldManager
from agent_actions.utilities.lineage import LineageBuilder

logger = logging.getLogger(__name__)


class LineageTrackingMixin:
    """
    Mixin class that provides standardized lineage tracking functionality.

    This mixin can be inherited by any processor class that needs to track
    lineage information across processing operations.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the mixin."""
        super().__init__(*args, **kwargs)
        # Get action_name from agent_config if available
        agent_config = getattr(self, "agent_config", {})
        self._action_name = agent_config.get("agent_type")
        if not self._action_name:
            self._action_name = "unknown_action"
            logger.warning(
                "No agent_type found in agent_config, using 'unknown_action' for lineage tracking"
            )

    def _get_action_name(self) -> str:
        """
        Get the action name for node ID generation.

        Returns:
            Action name
        """
        return self._action_name

    def generate_node_id(self) -> str:
        """
        Generate a node ID for this processor.

        Returns:
            Generated node ID in format {action_name}_{uuid}
        """
        return IDGenerator.generate_node_id(self._get_action_name())

    def add_lineage_to_item(self, item: Dict, source_item: Dict) -> Dict:
        """
        Add lineage tracking to an item based on a source item.

        Args:
            item: Item to add lineage to
            source_item: Source item containing existing lineage

        Returns:
            Item with lineage tracking added
        """
        node_id = self.generate_node_id()
        return LineageBuilder.add_lineage_tracking(item, source_item, node_id)

    def add_context_lineage_to_item(self, item: Dict, context_data: Any) -> Dict:
        """
        Add lineage tracking to an item based on context data.

        Args:
            item: Item to add lineage to
            context_data: Context data that may contain lineage

        Returns:
            Item with lineage tracking added
        """
        node_id = self.generate_node_id()
        return LineageBuilder.add_context_lineage_tracking(item, context_data, node_id)

    def add_lineage_to_items(self, items: List[Dict], source_item: Dict) -> List[Dict]:
        """
        Add lineage tracking to multiple items with unique node IDs.

        When a processor outputs multiple items from a single input (e.g., split operations),
        each output item gets a unique node_id by appending a sub-index to distinguish them.
        This enables accurate historical data lookups for split records.

        Args:
            items: List of items to add lineage to
            source_item: Source item containing existing lineage

        Returns:
            List of items with lineage tracking added

        Examples:
            Single output: node_id = "node_5_abc123"
            Split outputs:
                - item[0]: node_id = "node_5_abc123_0"
                - item[1]: node_id = "node_5_abc123_1"
                - item[2]: node_id = "node_5_abc123_2"
        """
        if not items:
            return items

        base_node_id = self.generate_node_id()

        # If only one item, no sub-index needed
        if len(items) == 1:
            return [LineageBuilder.add_lineage_tracking(items[0], source_item, base_node_id)]

        # For multiple items (split records), append sub-index to each
        return [
            LineageBuilder.add_lineage_tracking(item, source_item, f"{base_node_id}_{idx}")
            for idx, item in enumerate(items)
        ]

    def create_processed_item_with_lineage(
        self,
        source_guid: str,
        content: Any,
        source_item: Optional[Dict] = None,
        context_data: Optional[Any] = None,
    ) -> Dict:
        """
        Create a processed item with lineage tracking.

        Args:
            source_guid: Source GUID for the item
            content: Content of the item
            source_item: Optional source item for lineage tracking
            context_data: Optional context data for lineage tracking

        Returns:
            Processed item with lineage tracking
        """
        node_id = self.generate_node_id()

        if source_item is not None:
            lineage = LineageBuilder.build_lineage(source_item, node_id)
        elif (
            context_data is not None
            and isinstance(context_data, dict)
            and "lineage" in context_data
        ):
            lineage = context_data["lineage"] + [node_id]
        else:
            lineage = [node_id]

        return FieldManager().create_processed_item(
            source_guid=source_guid, content=content, node_id=node_id, lineage=lineage
        )

    def ensure_items_have_required_fields(self, items: List[Dict], source_guid: str) -> List[Dict]:
        """
        Ensure all items have required fields (target_id, source_guid, node_id).

        Args:
            items: List of items to process
            source_guid: Source GUID to use for items missing it

        Returns:
            List of items with all required fields
        """
        field_manager = FieldManager()
        return [
            field_manager.ensure_required_fields(item, source_guid, self._get_processor_idx())
            for item in items
        ]
