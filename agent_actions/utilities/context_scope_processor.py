"""Context Scope Processor - Field flow control for LLM context and output.

This module provides utilities for processing context_scope configuration directives
that control how upstream action fields flow through the current action.

Supports four directives:
- static_data: Load external reference files, available in both prompt and LLM context
- observe: Fields added to LLM context, available in prompt templates (not in output unless in schema)
- drop: Fields blocked from LLM entirely (security/privacy)
- passthrough: Fields guaranteed in output (also available in templates)
"""

import json
import logging
from typing import Dict, List, Tuple, Any, Optional
from copy import deepcopy

logger = logging.getLogger(__name__)


class ContextScopeProcessor:
    """
    Handles context_scope processing for granular field flow control.

    This class provides static methods to:
    1. Parse field references in 'action.field' format
    2. Extract field values from nested field_context
    3. Apply context_scope rules to split field_context into 3 streams
    4. Format LLM context for message injection
    5. Merge passthrough fields into LLM output

    Example usage:
        context_scope = {
            'observe': ['action.reference_data'],
            'drop': ['source.api_key'],
            'passthrough': ['action.document_id']
        }

        prompt_ctx, llm_ctx, passthrough = ContextScopeProcessor.apply_context_scope(
            field_context, context_scope
        )
    """

    @staticmethod
    def parse_field_reference(field_ref: str) -> Tuple[str, str]:
        """
        Parse field reference in 'action.field' format.

        Args:
            field_ref: Field reference string (e.g., 'fact_extractor.document_id')

        Returns:
            Tuple of (action_name, field_name)

        Raises:
            ValueError: If field_ref is not in 'action.field' format

        Examples:
            >>> parse_field_reference('fact_extractor.document_id')
            ('fact_extractor', 'document_id')

            >>> parse_field_reference('source.page_content')
            ('source', 'page_content')

            >>> parse_field_reference('invalid')
            ValueError: Invalid field reference: 'invalid'. Expected format: 'action.field'
        """
        if not field_ref or not isinstance(field_ref, str):
            raise ValueError(
                f"Invalid field reference: {field_ref!r}. "
                f"Expected non-empty string in format 'action.field'"
            )

        parts = field_ref.split('.', 1)
        if len(parts) != 2:
            raise ValueError(
                f"Invalid field reference: '{field_ref}'. "
                f"Expected format: 'action.field' (with exactly one dot)"
            )

        action_name, field_name = parts

        if not action_name or not field_name:
            raise ValueError(
                f"Invalid field reference: '{field_ref}'. "
                f"Both action and field must be non-empty"
            )

        return (action_name, field_name)

    @staticmethod
    def extract_field_value(
        field_context: Dict,
        action_name: str,
        field_name: str
    ) -> Any:
        """
        Extract field value from nested field_context structure.

        Args:
            field_context: Nested dict with structure {action: {field: value}}
            action_name: Name of the action (e.g., 'fact_extractor')
            field_name: Name of the field (e.g., 'document_id')

        Returns:
            Field value if found, None otherwise

        Examples:
            >>> field_context = {
            ...     'source': {'page_content': 'text'},
            ...     'fact_extractor': {'document_id': '123', 'facts': [...]}
            ... }
            >>> extract_field_value(field_context, 'fact_extractor', 'document_id')
            '123'

            >>> extract_field_value(field_context, 'missing_action', 'field')
            None

            >>> extract_field_value(field_context, 'fact_extractor', 'missing_field')
            None
        """
        if not isinstance(field_context, dict):
            return None

        if action_name not in field_context:
            return None

        action_data = field_context[action_name]

        if not isinstance(action_data, dict):
            return None

        return action_data.get(field_name)

    @staticmethod
    def apply_context_scope(
        field_context: Dict,
        context_scope: Dict,
        static_data: Optional[Dict] = None
    ) -> Tuple[Dict, Dict, Dict]:
        """
        Apply context_scope rules to split field_context into 3 streams.

        This is the core method that implements the context_scope feature by:
        0. Processing static_data: Merge into prompt_context and llm_context
        1. Processing drop: Removes fields from prompt_context
        2. Processing observe: Adds to llm_context, KEEPS in prompt_context for template rendering
        3. Processing passthrough: Extracts to passthrough_fields, keeps in prompt_context for template access

        Args:
            field_context: Complete field context with all upstream action data
                          Structure: {action_name: {field: value, ...}, ...}
            context_scope: Context scope configuration with directives
                          Structure: {
                              'static_data': {'field_name': '$file:path', ...},
                              'observe': ['action.field', ...],
                              'drop': ['action.field', ...],
                              'passthrough': ['action.field', ...]
                          }
            static_data: Optional pre-loaded static data from files
                        Structure: {field_name: loaded_value, ...}

        Returns:
            Tuple of (prompt_context, llm_context, passthrough_fields):
            - prompt_context: Field context for {{ reference.field }} rendering (includes passthrough and static data)
            - llm_context: Fields for LLM additional context (includes static data)
            - passthrough_fields: Fields guaranteed in output, also available in prompt_context (flat dict)

        Examples:
            >>> field_context = {
            ...     'source': {'text': 'data', 'api_key': 'secret'},
            ...     'extractor': {'facts': [...], 'id': '123', 'meta': {...}}
            ... }
            >>> context_scope = {
            ...     'static_data': {'syllabus': '$file:syllabus.json'},
            ...     'observe': ['extractor.meta'],
            ...     'drop': ['source.api_key'],
            ...     'passthrough': ['extractor.id']
            ... }
            >>> static_data = {'syllabus': {'content': '...'}}
            >>> prompt_ctx, llm_ctx, passthrough = apply_context_scope(
            ...     field_context, context_scope, static_data
            ... )
            >>> # prompt_ctx: {source: {text: 'data'}, extractor: {facts: [...], meta: {...}, id: '123'}, seed: {syllabus: {...}}}
            >>> # llm_ctx: {syllabus: {...}, meta: {...}}
            >>> # passthrough: {id: '123'}
        """
        # Deep copy to avoid mutating original field_context
        prompt_context = deepcopy(field_context)
        llm_context = {}
        passthrough_fields = {}

        # Process STATIC_DATA: Add to both prompt_context and llm_context
        if static_data:
            logger.debug(f"[STATIC_DATA] Merging {len(static_data)} static data fields into context")
            logger.debug(f"[STATIC_DATA] Fields: {list(static_data.keys())}")

            # Add to llm_context (for LLM visibility)
            llm_context.update(static_data)

            # Add under 'seed' namespace in prompt_context (for field reference replacement)
            # This allows references like {seed.exam_syllabus} in prompts
            if 'seed' in prompt_context:
                logger.warning(
                    "Seed data namespace 'seed' conflicts with existing action. "
                    "Seed data will overwrite it."
                )
            prompt_context['seed'] = static_data
            logger.debug(f"[SEED_DATA] Added to prompt_context under 'seed' namespace")

        # Process DROP: Remove from prompt_context (security)
        for field_ref in context_scope.get('drop', []):
            try:
                action_name, field_name = ContextScopeProcessor.parse_field_reference(field_ref)

                # Remove from prompt_context
                if action_name in prompt_context and isinstance(prompt_context[action_name], dict):
                    prompt_context[action_name].pop(field_name, None)

            except ValueError:
                # Invalid reference, skip silently
                continue

        # Process OBSERVE: Extract to llm_context, KEEP in prompt_context for template rendering
        for field_ref in context_scope.get('observe', []):
            try:
                action_name, field_name = ContextScopeProcessor.parse_field_reference(field_ref)

                # Extract value from original field_context (before drop removed it)
                value = ContextScopeProcessor.extract_field_value(
                    field_context, action_name, field_name
                )

                if value is not None:
                    # Add to llm_context (flat dict with field names as keys)
                    llm_context[field_name] = value

                    # DO NOT remove from prompt_context - users need it for {{action.field}} template refs

            except ValueError:
                # Invalid reference, skip silently
                continue

        # Process PASSTHROUGH: Extract to passthrough_fields, remove from prompt_context
        for field_ref in context_scope.get('passthrough', []):
            try:
                action_name, field_name = ContextScopeProcessor.parse_field_reference(field_ref)

                # Extract value from original field_context
                value = ContextScopeProcessor.extract_field_value(
                    field_context, action_name, field_name
                )

                if value is not None:
                    # Add to passthrough_fields (flat dict with field names as keys)
                    passthrough_fields[field_name] = value

            except ValueError:
                # Invalid reference, skip silently
                continue

        return (prompt_context, llm_context, passthrough_fields)

    @staticmethod
    def format_llm_context(llm_context: Dict) -> str:
        """
        Format llm_context dict as readable text for LLM message injection.

        Converts a dictionary of context fields into a formatted string suitable
        for appending to LLM messages or system context.

        Args:
            llm_context: Dictionary of fields to send to LLM
                        Structure: {field_name: value, ...}

        Returns:
            Formatted string with each field on a new line, or empty string if no context

        Examples:
            >>> llm_context = {
            ...     'entities': ['entity1', 'entity2'],
            ...     'metadata': {'source': 'research', 'date': '2024-01-01'}
            ... }
            >>> print(format_llm_context(llm_context))
            Additional context:
            entities: [
              "entity1",
              "entity2"
            ]
            metadata: {
              "source": "research",
              "date": "2024-01-01"
            }

            >>> format_llm_context({})
            ''
        """
        if not llm_context:
            return ""

        lines = ["Additional context:"]

        for key, value in llm_context.items():
            # Format value as pretty JSON for readability
            value_str = json.dumps(value, indent=2, ensure_ascii=False)
            lines.append(f"{key}: {value_str}")

        return "\n".join(lines)

    @staticmethod
    def merge_passthrough_fields(
        llm_response: List[Dict],
        passthrough_fields: Dict
    ) -> List[Dict]:
        """
        Merge passthrough fields into LLM response (similar to observe logic).

        This method implements the passthrough directive by merging fields into
        the LLM's output structure. Works with both structured and flat responses.

        Args:
            llm_response: LLM response, can be:
                         - List of dicts with 'content' key (structured)
                         - List of flat dicts
                         - Single dict
            passthrough_fields: Fields to merge into output
                               Structure: {field_name: value, ...}

        Returns:
            LLM response with passthrough fields merged

        Note:
            Similar to ProcessorUtils.transform_with_observe() but for context_scope

        Examples:
            >>> llm_response = [
            ...     {'source_guid': 'guid1', 'content': {'classification': 'positive'}}
            ... ]
            >>> passthrough_fields = {'document_id': '123', 'filename': 'doc.pdf'}
            >>> result = merge_passthrough_fields(llm_response, passthrough_fields)
            >>> result[0]['content']
            {'classification': 'positive', 'document_id': '123', 'filename': 'doc.pdf'}

            >>> llm_response = {'classification': 'positive'}
            >>> passthrough_fields = {'document_id': '123'}
            >>> merge_passthrough_fields(llm_response, passthrough_fields)
            {'classification': 'positive', 'document_id': '123'}
        """
        if not passthrough_fields:
            # No passthrough fields to merge
            return llm_response

        # Handle list of items
        if isinstance(llm_response, list):
            for item in llm_response:
                if isinstance(item, dict):
                    # Check if structured format with 'content' key
                    if 'content' in item and isinstance(item['content'], dict):
                        # Merge into content
                        item['content'].update(passthrough_fields)
                    else:
                        # Merge directly into item
                        item.update(passthrough_fields)
            return llm_response

        # Handle single dict
        if isinstance(llm_response, dict):
            # Check if structured format with 'content' key
            if 'content' in llm_response and isinstance(llm_response['content'], dict):
                # Merge into content
                llm_response['content'].update(passthrough_fields)
            else:
                # Merge directly
                llm_response.update(passthrough_fields)
            return llm_response

        # Other types (shouldn't happen, but be defensive)
        return llm_response

    @staticmethod
    def build_field_context_with_history(
        contents: Dict,
        agent_name: str,
        agent_config: Dict,
        agent_indices: Optional[Dict[str, int]] = None,
        dependency_configs: Optional[Dict[str, Dict]] = None,
        source_content: Optional[Any] = None,
        loop_context: Optional[Dict] = None,
        workflow_metadata: Optional[Dict] = None,
        current_item: Optional[Dict] = None,
        file_path: Optional[str] = None
    ) -> Dict:
        """
        Build field context with agent namespaces from flat contents.

        Automatically loads ALL previous actions from lineage, making them available
        for field references. No manual dependencies declaration needed.

        Used by BOTH online and batch modes for consistent field context building.

        Args:
            contents: Flat dict containing all fields from dependencies
            agent_name: Name of the current agent
            agent_config: Configuration for the current agent
            agent_indices: Dict mapping agent names to their node indices
            dependency_configs: Dict mapping dependency names to their configs
            source_content: Optional source content for {source.field} references
            loop_context: Optional loop context for {loop.*} references
            workflow_metadata: Optional workflow metadata for {workflow.*} references
            current_item: Optional current item dict containing lineage and source_guid
            file_path: Optional file path for constructing historical node paths

        Returns:
            Namespaced field_context dict for replace_field_references()

        Example:
            Input contents (flat):
                {'bloom_details': '...', 'cluster_id': '...', 'page_content': '...'}

            Output field_context (namespaced):
                {
                    'source': {...},
                    'fact_extractor': {...},        # Auto-loaded from lineage
                    'flatten_facts': {...},         # Auto-loaded from lineage
                    'cluster_list': {...},          # Auto-loaded from lineage
                    'combine_by_cluster': {...},    # Auto-loaded from lineage
                    'loop': {...},
                    'workflow': {...}
                }
        """
        from agent_actions.utilities.llm_context_utils import LLMContextUtils
        from agent_actions.preprocessing.context.historical_node_loader import HistoricalNodeDataLoader

        field_context = {}

        # Load source content internally (unified for batch and realtime)
        # This ensures both modes get the ACTUAL source data from the source folder
        if current_item and file_path and agent_name:
            source_guid = current_item.get('source_guid')

            if source_guid:
                # Import required classes for source loading
                from agent_actions.input_loading.extractors_source_data_loader import SourceDataLoader
                from agent_actions.preprocessing.transformation.data_transformer import DataTransformer
                from agent_actions.state_management.path_manager import PathManager

                try:
                    # Initialize path manager and source loader
                    path_manager = PathManager(agent_name, file_path)
                    source_loader = SourceDataLoader(agent_name, path_manager)

                    # Load source data from the source folder
                    source_data = source_loader.load_source_data(file_path)

                    # Get the specific source item by source_guid
                    if source_data:
                        source_item = DataTransformer.get_content_by_source_guid(source_data, source_guid)
                        if source_item:
                            field_context['source'] = source_item
                except Exception as e:
                    # Fallback to passed source_content if loading fails
                    if source_content:
                        field_context['source'] = source_content
                    # Log the error but don't fail - some workflows may not have source folder
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.debug(f"Could not load source from folder: {e}")

        # Fallback: Use passed source_content if not loaded above
        # This maintains backward compatibility
        if 'source' not in field_context and source_content:
            field_context['source'] = source_content

        # Auto-load ALL previous actions from lineage
        if current_item and file_path and agent_indices:
            lineage = current_item.get('lineage', [])
            source_guid = current_item.get('source_guid')
            current_idx = agent_indices.get(agent_name, 999)

            if lineage and source_guid:
                # Iterate through ALL agents in agent_indices
                for action_name, action_idx in agent_indices.items():
                    # Only load actions that come BEFORE the current agent
                    if action_idx >= current_idx:
                        continue

                    # Load historical data for this action
                    historical_data = HistoricalNodeDataLoader.load_historical_node_data(
                        action_name=action_name,
                        lineage=lineage,
                        source_guid=source_guid,
                        file_path=file_path,
                        agent_indices=agent_indices,
                        caller_lineage=lineage
                    )

                    if historical_data:
                        field_context[action_name] = historical_data

        # Fallback: Also check declared dependencies for flat contents
        # (Backward compatibility for immediate predecessor data in contents)
        if dependency_configs:
            dependencies = agent_config.get('dependencies', [])
            for dep_name in dependencies:
                # Skip if already loaded from historical data
                if dep_name in field_context:
                    continue

                dep_config = dependency_configs.get(dep_name)
                if not dep_config:
                    continue

                # Load from flat contents (immediate predecessor)
                dep_output_fields = LLMContextUtils.compute_llm_context(dep_config)
                dep_fields = {}
                for field in dep_output_fields:
                    if field in contents:
                        dep_fields[field] = contents[field]

                if dep_fields:
                    field_context[dep_name] = dep_fields

        # Add loop and workflow contexts
        if loop_context:
            field_context['loop'] = loop_context
        if workflow_metadata:
            field_context['workflow'] = workflow_metadata

        return field_context
