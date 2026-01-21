"""Utility helpers shared across processors."""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple
from agent_actions.utils.udf_management.tooling import execute_user_defined_function
from agent_actions.llm.realtime import builder as agent_builder
from agent_actions.input.preprocessing.filtering.guard_filter import (
    get_global_guard_filter,
    FilterItemRequest,
)
from agent_actions.utils.transformation import PassthroughTransformer

logger = logging.getLogger(__name__)


def evaluate_guard_condition(agent_config: Dict, context: Any) -> Tuple[bool, Optional[str]]:
    """
    Evaluate guard conditions (where_clause, conditional_clause).

    This is a centralized function for guard evaluation that can be called
    BEFORE prompt rendering to avoid template errors when guards would skip.

    Args:
        agent_config: Agent configuration with guard conditions
        context: Context data for guard evaluation (should include upstream action data)

    Returns:
        Tuple of (should_execute, skip_behavior):
        - (True, None) = guard passed, proceed with execution
        - (False, 'skip') = guard failed with skip behavior, use passthrough
        - (False, 'filter') = guard failed with filter behavior, filter out entirely
    """
    # Check legacy conditional clause (UDF-based)
    conditional_result = _evaluate_conditional_clause(agent_config, context)
    if conditional_result is not None:
        return conditional_result

    # Check guard condition
    return _evaluate_guard(agent_config, context)


def _evaluate_conditional_clause(
    agent_config: Dict, context: Any
) -> Optional[Tuple[bool, Optional[str]]]:
    """Evaluate legacy conditional clause (UDF-based)."""
    conditional_clause = (agent_config.get("conditional_clause") or "").lower()
    if not conditional_clause:
        return None

    try:
        if not execute_user_defined_function(conditional_clause, context):
            logger.debug(
                "Guard: conditional_clause '%s' evaluated to False, skipping", conditional_clause
            )
            return (False, "skip")
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        logger.debug("Guard: conditional_clause evaluation failed: %s, proceeding", e)
        # Don't skip on UDF errors - proceed with execution

    return None


def _evaluate_guard(agent_config: Dict, context: Any) -> Tuple[bool, Optional[str]]:
    """Evaluate guard condition."""
    guard_config = agent_config.get("guard")
    if not guard_config:
        return (True, None)

    behavior = guard_config.get("behavior", "filter")
    clause = guard_config.get("clause")
    passthrough_on_error = guard_config.get("passthrough_on_error", True)

    if not clause:
        return (True, None)

    try:
        filter_service = get_global_guard_filter()
        request = FilterItemRequest(data=context, condition=clause)
        filter_result = filter_service.filter_item(request)
        return _process_filter_result(filter_result, behavior, passthrough_on_error, clause)

    except (ValueError, TypeError, KeyError, AttributeError) as e:
        logger.debug("Guard: guard condition evaluation exception: %s", e)
        return (True, None) if passthrough_on_error else (False, behavior)


def _process_filter_result(
    filter_result: Any, behavior: str, passthrough_on_error: bool, clause: str
) -> Tuple[bool, Optional[str]]:
    """Process filter result and return guard decision."""
    # Handle FilterResult object or boolean
    if hasattr(filter_result, "success") and not filter_result.success:
        # Evaluation failed
        if passthrough_on_error:
            logger.debug(
                "Guard: condition evaluation failed, proceeding (passthrough_on_error=True)"
            )
            return (True, None)
        logger.debug("Guard: condition evaluation failed, skipping (passthrough_on_error=False)")
        return (False, behavior)

    matched = filter_result.matched if hasattr(filter_result, "matched") else bool(filter_result)

    if not matched:
        logger.debug("Guard: condition '%s' not matched, behavior='%s'", clause, behavior)
        return (False, behavior)

    # All guards passed
    return (True, None)


def run_dynamic_agent(
    agent_config: Dict,
    agent_name: str,
    context: Any,
    formatted_prompt: str,
    *,
    tools_path: Optional[str] = None,
    tool_args: Optional[Dict[str, Any]] = None,
    source_content: Optional[Any] = None,
    llm_context: Optional[Any] = None,
    skip_guard_eval: bool = False,
) -> tuple[Any, bool]:
    """Execute an agent with conditional guard processing and data filtering.

    Handles both legacy conditional clauses (UDF-based) and modern guard conditions
    with skip behavior. When skip conditions are met, returns the original context
    unchanged without executing the agent.

    Data Structure Handling:
        When context has nested structure (e.g., {source_guid, content{}, target_id}),
        this function extracts the 'content' dict before sending to tools/guards. This ensures:
        - Metadata fields (source_guid, target_id, node_id, lineage) are available for guards
        - Only actual data fields from 'content' are used for evaluation

    Context Separation:
        This function receives TWO contexts:
        - context: Original, untransformed data for guard evaluation
        - llm_context: Transformed data (with context_scope.drop applied) for LLM/tool execution

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
        skip_guard_eval: If True, skip guard evaluation (already done by caller).
                        Used when guard was evaluated early (before prompt rendering).

    Returns:
        Tuple of (response/context, was_executed):
            - response/context: The response data or original context if skipped
            - was_executed: Whether the agent actually processed the data
    """
    # Skip guard evaluation if already done by caller (e.g., DataGenerator)
    if not skip_guard_eval:
        if _should_skip_legacy_conditional(agent_config, context):
            return (context, False)
        if _should_skip_guard(agent_config, context):
            return (context, False)
        if _should_filter_guard(agent_config, context):
            return (None, False)

    # Extract content from nested structure if needed (for tools/guards)
    if isinstance(context, dict) and "content" in context and isinstance(context["content"], dict):
        processed_context = context["content"]
    else:
        processed_context = context

    # Use llm_context if provided (transformed for LLM/tool), otherwise use processed_context
    llm_data = llm_context if llm_context is not None else processed_context

    # Pass both contexts to agent_builder (guards already ran on original data).
    response = agent_builder.create_dynamic_agent(
        agent_config,
        agent_name,
        llm_data,  # Send transformed context to LLM
        formatted_prompt,
        tools_path=tools_path,
        tool_args=tool_args,
        source_content=source_content,
        additional_context=None,
        original_context=processed_context,
    )

    # Note: passthrough fields are NOT merged here - they're merged later in
    # transform_with_observe() using the same pathway as observe directive
    # (via DataTransformer.update_schema_objects)

    return (response, True)


def _should_skip_legacy_conditional(agent_config: Dict, context: Any) -> bool:
    """Check if agent should be skipped based on legacy conditional clause."""
    conditional_clause = (agent_config.get("conditional_clause") or "").lower()
    if conditional_clause and (not execute_user_defined_function(conditional_clause, context)):
        return True
    return False


def _should_skip_guard(agent_config: Dict, context: Any) -> bool:
    """Check if agent should be skipped based on guard with skip behavior."""
    guard_config = agent_config.get("guard")
    if not (guard_config and guard_config.get("behavior") == "skip"):
        return False
    try:
        filter_service = get_global_guard_filter()
        request = FilterItemRequest(data=context, condition=guard_config["clause"])
        filter_result = filter_service.filter_item(request)
        return not filter_result.matched if filter_result.success else False
    except Exception as e:  # Intentional fallback
        logger.debug(
            "Guard skip check failed, using passthrough_on_error setting: %s",
            e,
            extra={"guard": guard_config.get("clause"), "operation": "guard_skip_check"},
        )
        passthrough_on_error = guard_config.get("passthrough_on_error", True)
        return passthrough_on_error


def _should_filter_guard(agent_config: Dict, context: Any) -> bool:
    """Check if item should be filtered out based on guard with filter behavior."""
    guard_config = agent_config.get("guard")
    if not (guard_config and guard_config.get("behavior") == "filter"):
        return False
    try:
        filter_service = get_global_guard_filter()
        request = FilterItemRequest(data=context, condition=guard_config["clause"])
        filter_result = filter_service.filter_item(request)
        if not filter_result.success:
            passthrough_on_error = guard_config.get("passthrough_on_error", True)
            return not passthrough_on_error
        return not filter_result.matched
    except Exception as e:  # Intentional fallback
        logger.debug(
            "Guard filter check failed, using passthrough_on_error setting: %s",
            e,
            extra={"guard": guard_config.get("clause"), "operation": "guard_filter_check"},
        )
        passthrough_on_error = guard_config.get("passthrough_on_error", True)
        return not passthrough_on_error


def transform_with_passthrough(
    data: List[Any],
    context_data: Dict[str, Any],
    source_guid: str,
    agent_config: Dict[str, Any],
    idx: int = 0,
    passthrough_fields: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> List[Any]:
    """Apply ``context_scope.passthrough`` logic to generated data consistently.

    Args:
        data: Generated data list
        context_data: Context data dictionary containing fields
        source_guid: Source GUID
        agent_config: Agent configuration containing context_scope
        idx: Index for node generation
        passthrough_fields: Optional pre-computed passthrough fields
        metadata: Optional LLM response metadata to add to output items

    Returns:
        Transformed data list with passthrough fields and metadata merged
    """
    transformer = PassthroughTransformer()
    return transformer.transform_with_passthrough(
        data,
        context_data,
        source_guid,
        agent_config,
        idx,
        passthrough_fields=passthrough_fields,
        metadata=metadata,
    )
