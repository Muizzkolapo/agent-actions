"""Utility helpers shared across processors."""
from __future__ import annotations
from typing import Any, Dict, Optional
from agent_actions.utilities.tooling import execute_user_defined_function
from agent_actions.llm_invocation.realtime import agent_builder
from agent_actions.response_processing.where_parser import get_global_filter
from .utils_processor_utils import ProcessorUtils

def apply_drops(contents: Any, agent_config: Dict) -> Any:
    """Apply ``drops`` transformations consistently."""
    return ProcessorUtils.apply_drops(contents, agent_config)

def run_dynamic_agent(agent_config: Dict, agent_name: str, context: Any, formatted_prompt: str, *, tools_path: Optional[str]=None, tool_args: Optional[Dict[str, Any]]=None, source_content: Optional[Any]=None, llm_additional_context: Optional[Dict]=None) -> tuple[Any, bool]:
    """Execute an agent with conditional guard processing and data filtering.

    Handles both legacy conditional clauses (UDF-based) and modern WHERE clauses
    with skip behavior. When skip conditions are met, returns the original context
    unchanged without executing the agent.

    Data Structure Handling:
        When context has nested structure (e.g., {source_guid, content{}, target_id}),
        this function extracts the 'content' dict before applying drops and sending
        to the LLM. This ensures:
        - Metadata fields (source_guid, target_id, node_id, lineage) never reach LLM
        - Only actual data fields from 'content' are sent to LLM
        - drops/observe configurations only affect fields inside 'content'

    Context Scope Support:
        Supports context_scope feature for granular field flow control:
        - llm_additional_context: Fields from context_scope.include merged into LLM context JSON
        - context_scope.passthrough: Handled later in transform_with_observe() (same pathway as observe)

    Args:
        agent_config: Agent configuration including guard conditions, drops, and observe
        agent_name: Name of the agent being executed
        context: Data context for agent execution. May be flat dict or nested structure
                 with 'content' key containing the actual data
        formatted_prompt: Formatted prompt for the agent
        tools_path: Optional path to tool functions
        tool_args: Optional tool arguments
        source_content: Optional source content
        llm_additional_context: Optional additional context for LLM (from context_scope.include)

    Returns:
        Tuple of (response/context, was_executed) where was_executed indicates
        whether the agent actually processed the data or was skipped.
    """
    if _should_skip_legacy_conditional(agent_config, context):
        return (context, False)
    if _should_skip_where_clause(agent_config, context):
        return (context, False)
    if _should_filter_where_clause(agent_config, context):
        return (None, False)
    # Apply drops first
    if isinstance(context, dict) and 'content' in context and isinstance(context['content'], dict):
        content_dict = context['content']
        processed_context = apply_drops(content_dict, agent_config)
    else:
        processed_context = apply_drops(context, agent_config)

    # Then apply context_scope.exclude using same mechanism as drops
    context_scope = agent_config.get('context_scope', {})
    if context_scope and context_scope.get('exclude') and isinstance(processed_context, dict):
        from agent_actions.utilities.context_scope_processor import ContextScopeProcessor
        from agent_actions.preprocessing.data_transformer import DataTransformer

        # Extract field names from context_scope.exclude
        exclude_fields = []
        for field_ref in context_scope.get('exclude', []):
            try:
                _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
                exclude_fields.append(field_name)
            except ValueError:
                continue

        # Apply drops mechanism directly (same as apply_drops does)
        if exclude_fields:
            processed_context = DataTransformer.remove_schema_objects(processed_context, exclude_fields)

    # Merge context_scope.include fields into context JSON (not as text to prompt)
    if llm_additional_context and isinstance(processed_context, dict):
        print(f"\n[DEBUG] Merging llm_additional_context into processed_context:")
        print(f"  Include fields: {list(llm_additional_context.keys())}")
        processed_context = {**processed_context, **llm_additional_context}
        print(f"  Context keys after merge: {list(processed_context.keys())}")

    response = agent_builder.create_dynamic_agent(agent_config, agent_name, processed_context, formatted_prompt, tools_path=tools_path, tool_args=tool_args, source_content=source_content, additional_context=None)

    # Note: passthrough fields are NOT merged here - they're merged later in transform_with_observe()
    # using the same pathway as observe directive (via DataTransformer.update_schema_objects)

    return (response, True)

def _should_skip_legacy_conditional(agent_config: Dict, context: Any) -> bool:
    """Check if agent should be skipped based on legacy conditional clause."""
    conditional_clause = (agent_config.get('conditional_clause') or '').lower()
    if conditional_clause and (not execute_user_defined_function(conditional_clause, context)):
        return True
    return False

def _should_skip_where_clause(agent_config: Dict, context: Any) -> bool:
    """Check if agent should be skipped based on WHERE clause with skip behavior."""
    where_clause_config = agent_config.get('where_clause')
    if not (where_clause_config and where_clause_config.get('behavior') == 'skip'):
        return False
    try:
        filter_service = get_global_filter()
        filter_matched = filter_service.filter_item(context, where_clause_config['clause'])
        return not filter_matched
    except Exception:
        passthrough_on_error = where_clause_config.get('passthrough_on_error', True)
        return passthrough_on_error

def _should_filter_where_clause(agent_config: Dict, context: Any) -> bool:
    """Check if item should be filtered out based on WHERE clause with filter behavior."""
    where_clause_config = agent_config.get('where_clause')
    if not (where_clause_config and where_clause_config.get('behavior') == 'filter'):
        return False
    try:
        filter_service = get_global_filter()
        filter_result = filter_service.filter_item(context, where_clause_config['clause'])
        if hasattr(filter_result, 'success'):
            if not filter_result.success:
                passthrough_on_error = where_clause_config.get('passthrough_on_error', True)
                return not passthrough_on_error
            return not filter_result.matched
        else:
            return not filter_result
    except Exception:
        passthrough_on_error = where_clause_config.get('passthrough_on_error', True)
        return not passthrough_on_error

def transform_with_observe(data: list, context_data: dict, source_guid: str, agent_config: Dict, idx: int=0) -> list:
    """Apply ``observe`` logic to generated data consistently."""
    return ProcessorUtils.transform_with_observe(data, context_data, source_guid, agent_config, idx)