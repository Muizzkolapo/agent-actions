"""
Common utility class for processor operations.

This module provides shared functionality for processors including:
- UUID generation utilities
- Transform operations
- Lineage tracking operations
"""

import uuid
import json
from typing import Dict, List, Any, Optional, Union

from agent_actions.common.transformers.data_transformer import DataTransformer
from agent_actions.constants import SIDE_COLLECTION_KEY


class ProcessorUtils:
    """Utility class containing common operations shared across processors."""

    @staticmethod
    def generate_target_id() -> str:
        """
        Generate a unique target ID.
        
        Returns:
            A UUID4 string for use as target_id
        """
        return str(uuid.uuid4())

    @staticmethod
    def generate_node_id(idx: int) -> str:
        """
        Generate a unique node ID with index prefix.
        
        Args:
            idx: Index to include in the node ID
            
        Returns:
            A node ID in the format "node_{idx}_{uuid}"
        """
        return f"node_{idx}_{uuid.uuid4()}"

    @staticmethod
    def generate_deterministic_source_guid(content: Any) -> str:
        """
        Generate a deterministic source GUID based on content.
        
        Args:
            content: Content to generate GUID from
            
        Returns:
            A deterministic UUID5 string
        """
        if isinstance(content, dict):
            content_for_hash = json.dumps(content, sort_keys=True)
        else:
            content_for_hash = str(content)
        return str(uuid.uuid5(uuid.NAMESPACE_OID, content_for_hash))

    @staticmethod
    def ensure_required_fields(obj: Dict, source_guid: str, idx: int = 0) -> Dict:
        """
        Ensure an object has all required fields (target_id, source_guid, node_id).
        
        Args:
            obj: Object to update
            source_guid: Source GUID to use if missing
            idx: Index for node_id generation
            
        Returns:
            Updated object with all required fields
        """
        obj = obj.copy()  # Don't modify original
        
        if 'target_id' not in obj or not obj['target_id']:
            obj['target_id'] = ProcessorUtils.generate_target_id()
        if 'source_guid' not in obj or not obj['source_guid']:
            obj['source_guid'] = source_guid
        if 'node_id' not in obj or not obj['node_id']:
            obj['node_id'] = ProcessorUtils.generate_node_id(idx)
            
        return obj

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
        return [nid for nid in lineage if isinstance(nid, str) and nid.startswith('node_')]

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
            filtered_lineage = ProcessorUtils.filter_node_lineage(item['lineage'])
            return filtered_lineage + [node_id]
        else:
            return [node_id]

    @staticmethod
    def add_lineage_tracking(obj: Dict, item: Dict, node_id: str) -> Dict:
        """
        Add lineage tracking to an object based on source item.
        
        Args:
            obj: Object to add lineage to
            item: Source item containing lineage
            node_id: Node ID to append to lineage
            
        Returns:
            Object with lineage tracking added
        """
        obj = obj.copy()  # Don't modify original
        obj['node_id'] = node_id
        obj['lineage'] = ProcessorUtils.build_lineage(item, node_id)
        return obj

    @staticmethod
    def add_context_lineage_tracking(obj: Dict, context_data: Any, node_id: str) -> Dict:
        """
        Add lineage tracking to an object based on context data.
        
        Args:
            obj: Object to add lineage to
            context_data: Context data that may contain lineage
            node_id: Node ID to append to lineage
            
        Returns:
            Object with lineage tracking added
        """
        obj = obj.copy()  # Don't modify original
        obj['node_id'] = node_id
        
        if isinstance(context_data, dict) and "lineage" in context_data:
            obj["lineage"] = context_data["lineage"] + [node_id]
        else:
            obj["lineage"] = [node_id]
            
        return obj

    @staticmethod
    def create_processed_item(
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
            'target_id': target_id or ProcessorUtils.generate_target_id(),
            'node_id': node_id or ProcessorUtils.generate_node_id(0),
            'lineage': lineage or []
        }

    @staticmethod
    def apply_remove_collection(contents: Any, agent_config: Dict) -> Any:
        """
        Apply remove_collection transformations consistently.
        
        Args:
            contents: Content to transform
            agent_config: Agent configuration containing remove_collection
            
        Returns:
            Transformed content
        """
        remove_collection = agent_config.get("remove_collection", [])
        if remove_collection and isinstance(contents, dict):
            return DataTransformer.remove_schema_objects(contents, remove_collection)
        return contents

    @staticmethod
    def transform_with_side_collection(
        data: List,
        context_data: Dict,
        source_guid: str,
        agent_config: Dict,
        idx: int = 0,
    ) -> List:
        """
        Apply side_collection logic to generated data consistently.
        
        Args:
            data: Generated data list
            context_data: Context data dictionary
            source_guid: Source GUID
            agent_config: Agent configuration
            idx: Index for node generation
            
        Returns:
            Transformed data list
        """
        # Ensure data is a list for consistent processing
        if not isinstance(data, list):
            # If data is a string or other type, wrap it in a list
            data = [data] if data is not None else []
        
        # Check if data already has the correct structure
        # (i.e., list of dicts with 'source_guid' and 'content' keys)
        already_structured = (
            len(data) > 0 and
            all(
                isinstance(item, dict) and 
                'source_guid' in item and 
                'content' in item 
                for item in data
            )
        )
        
        side_collection = agent_config.get(SIDE_COLLECTION_KEY, [])

        if already_structured and not side_collection:
            # Data already has correct structure, just ensure required fields
            output = data
        elif side_collection:
            # Apply side_collection logic
            if already_structured:
                # Extract content from structured data for side_collection processing
                contents = [item['content'] for item in data]
                updated = [
                    DataTransformer.update_schema_objects(context_data, content, side_collection)
                    for content in contents
                ]
            else:
                updated = [
                    DataTransformer.update_schema_objects(context_data, item, side_collection)
                    for item in data
                ]
            output = DataTransformer.transform_structure([{source_guid: updated}])
        else:
            # Apply transform_structure to ensure consistent output format
            output = DataTransformer.transform_structure([{source_guid: data}])
        
        # Ensure every output object has required fields
        for i, obj in enumerate(output):
            output[i] = ProcessorUtils.ensure_required_fields(obj, source_guid, idx)
        return output

    @staticmethod
    def create_conditional_response(
        source_guid: str,
        content: Any,
        idx: int = 0,
        item: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Create a standard response for when conditional clause fails.
        
        Args:
            source_guid: Source GUID
            content: Original content to preserve
            idx: Index for node generation
            item: Optional source item for lineage tracking
            
        Returns:
            List containing single processed item
        """
        node_id = ProcessorUtils.generate_node_id(idx)
        lineage = ProcessorUtils.build_lineage(item, node_id) if item else [node_id]
        
        return [ProcessorUtils.create_processed_item(
            source_guid=source_guid,
            content=content,
            node_id=node_id,
            lineage=lineage
        )]