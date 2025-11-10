"""Utility helpers shared across processors."""
from __future__ import annotations
from typing import Any, Dict, Optional
from agent_actions.utilities.tooling import execute_user_defined_function
from agent_actions.llm_invocation.realtime import agent_builder
from agent_actions.response_processing.where_parser import get_global_filter
from agent_actions.utilities.transformation import PassthroughTransformer

def run_dynamic_agent(agent_config: Dict, agent_name: str, context: Any, formatted_prompt: str, *, tools_path: Optional[str]=None, tool_args: Optional[Dict[str, Any]]=None, source_content: Optional[Any]=None, llm_context: Optional[Any]=None) -> tuple[Any, bool]:
    """Execute an agent with conditional guard processing and data filtering.

    Handles both legacy conditional clauses (UDF-based) and modern WHERE clauses
    with skip behavior. When skip conditions are met, returns the original context
    unchanged without executing the agent.

    Data Structure Handling:
        When context has nested structure (e.g., {source_guid, content{}, target_id}),
        this function extracts the 'content' dict before sending to tools/guards. This ensures:
        - Metadata fields (source_guid, target_id, node_id, lineage) are available for guards
        - Only actual data fields from 'content' are used for evaluation

    Context Separation (Phase 2: Issue #487 - Critical Fix):
        This function now receives TWO contexts:
        - context: Original, untransformed data for guard evaluation and tools/UDFs
        - llm_context: Transformed data (with context_scope.drop applied) for the LLM

        This separation is CRITICAL because:
        - Guards/tools need access to ALL fields (even those in context_scope.drop)
        - LLM should only see transformed context (with context_scope.drop applied)

    Args:
        agent_config: Agent configuration including guard conditions
        agent_name: Name of the agent being executed
        context: Original data context for guard evaluation and tools/UDFs.
                 May be flat dict or nested structure with 'content' key.
        formatted_prompt: Formatted prompt for the agent (already has few-shot samples)
        tools_path: Optional path to tool functions
        tool_args: Optional tool arguments
        source_content: Optional source content
        llm_context: Optional transformed context for LLM (with context_scope applied).
                     If not provided, uses context for both guards and LLM.

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

    # Extract content from nested structure if needed (for tools/guards)
    if isinstance(context, dict) and 'content' in context and isinstance(context['content'], dict):
        processed_context = context['content']
    else:
        processed_context = context

    # Use llm_context if provided (transformed for LLM), otherwise use processed_context
    # This allows context_scope.drop to work correctly while keeping original data for tools
    llm_data = llm_context if llm_context is not None else processed_context

    # CRITICAL FIX: Pass both contexts to agent_builder
    # - llm_data: Transformed context for LLM (has context_scope.drop applied)
    # - processed_context: Original context for tools/UDFs (has all fields from previous actions)
    response = agent_builder.create_dynamic_agent(
        agent_config,
        agent_name,
        llm_data,  # Send transformed context to LLM
        formatted_prompt,
        tools_path=tools_path,
        tool_args=tool_args,
        source_content=source_content,
        additional_context=None,
        original_context=processed_context  # CRITICAL: Pass original context for tools
    )

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

def transform_with_passthrough(data: list, context_data: dict, source_guid: str, agent_config: Dict, idx: int=0, passthrough_fields: Optional[Dict]=None) -> list:
    """Apply ``context_scope.passthrough`` logic to generated data consistently."""
    transformer = PassthroughTransformer()
    return transformer.transform_with_passthrough(data, context_data, source_guid, agent_config, idx, passthrough_fields=passthrough_fields)