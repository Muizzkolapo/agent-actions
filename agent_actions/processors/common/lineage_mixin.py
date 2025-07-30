"""
Lineage tracking mixin for processors.

This module provides a mixin class that standardizes lineage tracking
operations across different processor implementations.
"""

from typing import Dict, List, Any, Optional
from .processor_utils import ProcessorUtils


class LineageTrackingMixin:
    """
    Mixin class that provides standardized lineage tracking functionality.
    
    This mixin can be inherited by any processor class that needs to track
    lineage information across processing operations.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the mixin."""
        super().__init__(*args, **kwargs)
        # Get idx from agent_config if available
        self._idx = getattr(self, 'idx', None) or (
            getattr(self, 'agent_config', {}).get('idx', 0)
        )

    def _get_processor_idx(self) -> int:
        """
        Get the processor index for node ID generation.
        
        Returns:
            Processor index
        """
        return self._idx

    def generate_node_id(self) -> str:
        """
        Generate a node ID for this processor.
        
        Returns:
            Generated node ID
        """
        return ProcessorUtils.generate_node_id(self._get_processor_idx())

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
        return ProcessorUtils.add_lineage_tracking(item, source_item, node_id)

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
        return ProcessorUtils.add_context_lineage_tracking(item, context_data, node_id)

    def add_lineage_to_items(self, items: List[Dict], source_item: Dict) -> List[Dict]:
        """
        Add lineage tracking to multiple items using the same node ID.
        
        Args:
            items: List of items to add lineage to
            source_item: Source item containing existing lineage
            
        Returns:
            List of items with lineage tracking added
        """
        if not items:
            return items
            
        node_id = self.generate_node_id()
        return [
            ProcessorUtils.add_lineage_tracking(item, source_item, node_id)
            for item in items
        ]

    def create_processed_item_with_lineage(
        self,
        source_guid: str,
        content: Any,
        source_item: Optional[Dict] = None,
        context_data: Optional[Any] = None
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
            lineage = ProcessorUtils.build_lineage(source_item, node_id)
        elif context_data is not None and isinstance(context_data, dict) and "lineage" in context_data:
            lineage = context_data["lineage"] + [node_id]
        else:
            lineage = [node_id]
            
        return ProcessorUtils.create_processed_item(
            source_guid=source_guid,
            content=content,
            node_id=node_id,
            lineage=lineage
        )

    def ensure_items_have_required_fields(
        self, 
        items: List[Dict], 
        source_guid: str
    ) -> List[Dict]:
        """
        Ensure all items have required fields (target_id, source_guid, node_id).
        
        Args:
            items: List of items to process
            source_guid: Source GUID to use for items missing it
            
        Returns:
            List of items with all required fields
        """
        return [
            ProcessorUtils.ensure_required_fields(item, source_guid, self._get_processor_idx())
            for item in items
        ]