"""
Common utility class for processor operations.

This module provides shared functionality for processors including:
- UUID generation utilities
- Transform operations
- Lineage tracking operations
"""

import uuid
import json
import threading
import hashlib
from typing import Dict, List, Any, Optional

from agent_actions.agents.transformers.data_transformer import DataTransformer
from agent_actions.core.constants import OBSERVE_KEY


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
    def apply_drops(contents: Any, agent_config: Dict) -> Any:
        """
        Apply drops transformations consistently.

        drops (from config 'drops') specifies fields that should be:
        - Excluded from the LLM prompt
        - Removed from the final output

        Args:
            contents: Content to transform
            agent_config: Agent configuration containing drops

        Returns:
            Transformed content with removed fields
        """
        drops = agent_config.get("drops", [])
        if drops and isinstance(contents, dict):
            return DataTransformer.remove_schema_objects(contents, drops)
        return contents

    @staticmethod
    def transform_with_observe(
        data: List,
        context_data: Dict,
        source_guid: str,
        agent_config: Dict,
        idx: int = 0,
    ) -> List:
        """
        Apply observe logic to generated data consistently.

        observe (from config 'observe') specifies fields that should be:
        - Excluded from the LLM prompt
        - Included in the final output (passthrough from context)

        Args:
            data: Generated data list
            context_data: Context data dictionary containing observe fields
            source_guid: Source GUID
            agent_config: Agent configuration containing observe
            idx: Index for node generation

        Returns:
            Transformed data list with observe fields merged
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
        
        observe = agent_config.get(OBSERVE_KEY, [])

        if already_structured and not observe:
            # Data already has correct structure, just ensure required fields
            output = data
        elif observe:
            # Apply observe logic
            # If context_data has nested 'content' structure, extract it for observe fields.
            # This is critical: observe fields are user data inside 'content', not metadata
            # at the top level (source_guid, target_id, etc.)
            context_for_observe = context_data
            if isinstance(context_data, dict) and 'content' in context_data and isinstance(context_data['content'], dict):
                # Extract content dict so we look for observe fields in the right place
                # e.g., context_data['content']['question'] instead of context_data['question']
                context_for_observe = context_data['content']

            if already_structured:
                # Extract content from structured data for observe processing
                contents = [item['content'] for item in data]
                updated = []
                for content in contents:
                    if isinstance(content, dict):
                        updated.append(DataTransformer.update_schema_objects(context_for_observe, content, observe))
                    else:
                        # Convert non-dict content to dict format for processing
                        content_dict = {"content": content}
                        updated.append(DataTransformer.update_schema_objects(context_for_observe, content_dict, observe))
            else:
                updated = []
                for item in data:
                    if isinstance(item, dict):
                        updated.append(DataTransformer.update_schema_objects(context_for_observe, item, observe))
                    else:
                        # Convert non-dict items to dict format for processing
                        item_dict = {"content": item}
                        updated.append(DataTransformer.update_schema_objects(context_for_observe, item_dict, observe))
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

    # Class-level registry for loop correlation IDs
    _loop_correlation_registry: Dict[str, str] = {}
    _loop_correlation_lock = threading.RLock()

    @staticmethod
    def get_or_create_loop_correlation_id(source_guid: str, loop_base_name: str, workflow_session_id: str) -> str:
        """
        Get or create a loop correlation ID for a given source_guid within a loop context.

        Args:
            source_guid: Source GUID of the record
            loop_base_name: Base name of the loop (e.g., 'generate_distractors')
            workflow_session_id: Workflow session identifier for deterministic correlation

        Returns:
            Consistent loop correlation ID for this source_guid + loop + session combination
        """
        # Create a session-scoped key that combines workflow session with loop context
        registry_key = f"{workflow_session_id}:{loop_base_name}:{source_guid}"

        with ProcessorUtils._loop_correlation_lock:
            if registry_key not in ProcessorUtils._loop_correlation_registry:
                # Generate deterministic correlation ID instead of random UUID
                content = f"{loop_base_name}:{source_guid}"
                ProcessorUtils._loop_correlation_registry[registry_key] = ProcessorUtils._generate_deterministic_correlation_id(
                    workflow_session_id, content
                )

            return ProcessorUtils._loop_correlation_registry[registry_key]

    @staticmethod
    def get_or_create_position_based_loop_correlation_id(
        record_index: int,
        loop_base_name: str,
        workflow_session_id: str,
        file_context: str = ""
    ) -> str:
        """
        Get or create a loop correlation ID based on record position.

        Args:
            record_index: Position/index of the record in the input list
            loop_base_name: Base name of the loop (e.g., 'generate_distractors')
            workflow_session_id: Workflow session identifier for deterministic correlation
            file_context: Optional file context for uniqueness

        Returns:
            Consistent loop correlation ID for this position across all loop iterations
        """
        # Create a session-scoped key that combines workflow session with position context
        registry_key = f"{workflow_session_id}:{loop_base_name}:position_{record_index}:{file_context}"

        with ProcessorUtils._loop_correlation_lock:
            if registry_key not in ProcessorUtils._loop_correlation_registry:
                # Generate deterministic correlation ID instead of random UUID
                content = f"{loop_base_name}:position_{record_index}:{file_context}"
                ProcessorUtils._loop_correlation_registry[registry_key] = ProcessorUtils._generate_deterministic_correlation_id(
                    workflow_session_id, content
                )

            return ProcessorUtils._loop_correlation_registry[registry_key]

    @staticmethod
    def _generate_deterministic_correlation_id(workflow_session_id: str, content: str) -> str:
        """
        Generate a deterministic correlation ID based on session and content.
        
        Args:
            workflow_session_id: The workflow session identifier
            content: The content to hash (loop_base_name:source_guid or position info)
            
        Returns:
            Deterministic correlation ID in format: corr_{16_char_hash}
        """
        hash_input = f"{workflow_session_id}:{content}"
        hash_digest = hashlib.sha256(hash_input.encode()).hexdigest()
        return f"corr_{hash_digest[:16]}"
    

    @staticmethod
    def clear_loop_correlation_registry():
        """Clear the loop correlation ID registry (useful for testing or workflow resets)."""
        with ProcessorUtils._loop_correlation_lock:
            ProcessorUtils._loop_correlation_registry.clear()

    @staticmethod
    def add_loop_correlation_id(obj: Dict, agent_config: Dict, record_index: Optional[int] = None) -> Dict:
        """
        Add loop correlation ID to an object if the agent is part of a loop.

        Args:
            obj: Object to potentially add loop correlation ID to
            agent_config: Agent configuration to check for loop metadata
            record_index: Optional position/index of the record in the input list

        Returns:
            Object with loop correlation ID added if applicable
        """
        # Check if this is a loop agent
        if not agent_config.get('is_loop_agent', False):
            return obj

        loop_base_name = agent_config.get('loop_base_name')
        if not loop_base_name:
            return obj

        # Extract workflow session ID from agent_config
        workflow_session_id = agent_config.get('workflow_session_id')
        if not workflow_session_id:
            raise ValueError(
                "Missing workflow_session_id in agent_config. "
                "This is required for deterministic correlation IDs. "
                "Ensure AgentWorkflow properly injects session IDs."
            )

        obj = obj.copy()  # Don't modify original

        # Prefer position-based correlation ID if record_index is provided
        if record_index is not None:
            # Use position-based ID for better correlation across loops
            obj['loop_correlation_id'] = ProcessorUtils.get_or_create_position_based_loop_correlation_id(
                record_index, loop_base_name, workflow_session_id
            )
        else:
            # Fallback to source_guid-based correlation (original behavior)
            source_guid = obj.get('source_guid')
            if source_guid:
                obj['loop_correlation_id'] = ProcessorUtils.get_or_create_loop_correlation_id(
                    source_guid, loop_base_name, workflow_session_id
                )

        return obj