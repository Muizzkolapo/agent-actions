"""Utility helpers shared across processors."""
from __future__ import annotations
from typing import Any, Dict, Optional

from agent_actions.core.tooling import execute_user_defined_function
from agent_actions.agents.base import agent_builder
from agent_actions.core.parser.where_parser import get_global_filter
from .processor_utils import ProcessorUtils


def apply_drops(contents: Any, agent_config: Dict) -> Any:
    """Apply ``drops`` transformations consistently."""
    return ProcessorUtils.apply_drops(contents, agent_config)


def run_dynamic_agent(
    agent_config: Dict,
    agent_name: str,
    context: Any,
    formatted_prompt: str,
    *,
    tools_path: Optional[str] = None,
    tool_args: Optional[Dict[str, Any]] = None,
    source_content: Optional[Any] = None,
) -> tuple[Any, bool]:
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

    Args:
        agent_config: Agent configuration including guard conditions, drops, and observe
        agent_name: Name of the agent being executed
        context: Data context for agent execution. May be flat dict or nested structure
                 with 'content' key containing the actual data
        formatted_prompt: Formatted prompt for the agent
        tools_path: Optional path to tool functions
        tool_args: Optional tool arguments
        source_content: Optional source content

    Returns:
        Tuple of (response/context, was_executed) where was_executed indicates
        whether the agent actually processed the data or was skipped.
    """
    # Check legacy conditional clause (UDF-based skip behavior)
    if _should_skip_legacy_conditional(agent_config, context):
        return context, False

    # Check WHERE clause with skip behavior
    if _should_skip_where_clause(agent_config, context):
        return context, False

    # Check WHERE clause with filter behavior
    if _should_filter_where_clause(agent_config, context):
        return None, False  # Return None to indicate filtered out

    # Execute agent after all guard checks pass
    # If context has a 'content' dict, extract and apply drops to it
    if isinstance(context, dict) and 'content' in context and isinstance(context['content'], dict):
        # Extract the content dict and apply drops to it
        # The LLM should ONLY see the content, not metadata (source_guid, target_id, node_id, lineage)
        content_dict = context['content']
        processed_context = apply_drops(content_dict, agent_config)
    else:
        # Flat structure - apply drops directly
        processed_context = apply_drops(context, agent_config)

    response = agent_builder.create_dynamic_agent(
        agent_config,
        agent_name,
        processed_context,
        formatted_prompt,
        tools_path=tools_path,
        tool_args=tool_args,
        source_content=source_content,
    )
    return response, True


def _should_skip_legacy_conditional(agent_config: Dict, context: Any) -> bool:
    """Check if agent should be skipped based on legacy conditional clause."""
    conditional_clause = (agent_config.get("conditional_clause") or "").lower()

    if conditional_clause and not execute_user_defined_function(conditional_clause, context):
        return True
    return False


def _should_skip_where_clause(agent_config: Dict, context: Any) -> bool:
    """Check if agent should be skipped based on WHERE clause with skip behavior."""
    where_clause_config = agent_config.get("where_clause")

    if not (where_clause_config and where_clause_config.get("behavior") == "skip"):
        return False

    try:
        filter_service = get_global_filter()
        filter_matched = filter_service.filter_item(context, where_clause_config["clause"])
        return not filter_matched
    except Exception:
        # On error, check passthrough_on_error setting
        passthrough_on_error = where_clause_config.get("passthrough_on_error", True)
        return passthrough_on_error


def _should_filter_where_clause(agent_config: Dict, context: Any) -> bool:
    """Check if item should be filtered out based on WHERE clause with filter behavior."""
    where_clause_config = agent_config.get("where_clause")

    if not (where_clause_config and where_clause_config.get("behavior") == "filter"):
        return False

    try:
        filter_service = get_global_filter()
        filter_result = filter_service.filter_item(context, where_clause_config["clause"])
        
        if hasattr(filter_result, 'success'):
            # FilterResult object
            if not filter_result.success:
                # Handle filter error based on configuration
                passthrough_on_error = where_clause_config.get("passthrough_on_error", True)
                return not passthrough_on_error  # Filter out if passthrough_on_error is False
            # Item should be filtered out if condition doesn't match
            return not filter_result.matched
        else:
            # Boolean return (legacy)
            return not filter_result
    except Exception:
        # On error, check passthrough_on_error setting
        passthrough_on_error = where_clause_config.get("passthrough_on_error", True)
        return not passthrough_on_error  # Filter out if passthrough_on_error is False


def transform_with_observe(
    data: list,
    context_data: dict,
    source_guid: str,
    agent_config: Dict,
    idx: int = 0,
) -> list:
    """Apply ``observe`` logic to generated data consistently."""
    return ProcessorUtils.transform_with_observe(
        data, context_data, source_guid, agent_config, idx
    )

