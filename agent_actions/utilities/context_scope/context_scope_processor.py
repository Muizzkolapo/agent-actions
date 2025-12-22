"""
Context Scope Processor - Field flow control for LLM context and output.

Processes context_scope directives: static_data, observe, drop, passthrough.
"""
# pylint: disable=line-too-long,import-outside-toplevel,broad-exception-caught
# Line-too-long: Complex data transformations require descriptive variable names
# Import-outside-toplevel: Avoid circular imports
# Broad-exception-caught: Intentional fallback behavior for data processing

import json
import logging
from typing import Dict, List, Tuple, Any, Optional
from copy import deepcopy

logger = logging.getLogger(__name__)


class ContextScopeProcessor:
    """Processes context_scope configuration for field flow control."""

    @staticmethod
    def parse_field_reference(field_ref: str) -> Tuple[str, str]:
        """Parse field reference in 'action.field' format, returning (action_name, field_name)."""
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
    def extract_field_names_from_references(
        field_refs: List[str],
        return_type: str = 'list'
    ) -> List[str]:
        """
        Extract field names from list of field references.

        Args:
            field_refs: List of references in 'action.field' format
            return_type: Return type ('list' or other - currently only 'list' supported)

        Returns:
            List of field names extracted from references

        Example:
            ['generate_summary.key_concepts', 'extract.facts'] -> ['key_concepts', 'facts']
        """
        field_names = []

        for field_ref in field_refs:
            try:
                _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
                field_names.append(field_name)
            except ValueError:
                # Skip invalid references
                continue

        return field_names

    @staticmethod
    def extract_field_value(
        field_context: Dict,
        action_name: str,
        field_name: str
    ) -> Any:
        """Extract field value from nested field_context structure, returning None if not found."""
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
        """Apply context_scope rules, returning (prompt_context, llm_context, passthrough_fields)."""
        # Deep copy to avoid mutating original field_context
        prompt_context = deepcopy(field_context)
        llm_context = {}
        passthrough_fields = {}

        # Process STATIC_DATA: Add to both prompt_context and llm_context
        if static_data:
            logger.debug("[STATIC_DATA] Merging %s static data fields into context", len(static_data))
            logger.debug("[STATIC_DATA] Fields: %s", list(static_data.keys()))

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
            logger.debug("[SEED_DATA] Added to prompt_context under 'seed' namespace")

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
        """Format llm_context dict as readable text for LLM message injection."""
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
        """Merge passthrough fields into LLM response."""
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
    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    # pylint: disable=too-many-branches,too-many-statements
    # Complex field context building with historical data requires all these parameters
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
        """Build field context with agent namespaces, auto-loading previous actions from lineage."""
        from agent_actions.utilities.context_scope.llm_context_utils import LLMContextUtils
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
                    logger.debug("Could not load source from folder: %s", e)

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
