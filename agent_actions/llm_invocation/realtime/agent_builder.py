"""
Agent builder module for dynamic LLM agent invocation.

This module provides the main entry point for creating and executing dynamic agents
with support for multiple LLM vendors.
"""

import json
import sys
from typing import Dict, Any, Optional, List, Union
from agent_actions.utilities.constants import MODEL_VENDOR_KEY
from .services import (
    PromptService,
    ContextService,
    SchemaService,
    ClientInvocationService,
)


def create_dynamic_agent(
    agent_config: Dict[str, Any],
    udf: Any,
    context_data_str: Union[str, Dict],
    formatted_prompt: Optional[str] = None,
    tools_path: Optional[str] = None,
    tool_args: Optional[Dict[str, Any]] = None,
    source_content: Optional[Any] = None,
    additional_context: Optional[Dict] = None,
    original_context: Optional[Union[str, Dict]] = None,
) -> List[Any]:
    """
    Build and execute a prompt against the selected vendor.

    Args:
        agent_config: Agent configuration with model/prompt settings
        udf: User defined function (agent_name)
        context_data_str: Context data for LLM (may be transformed with
                         context_scope.drop applied)
        formatted_prompt: Pre-formatted prompt (optional, from DataGenerator)
        tools_path: Path to tool functions (optional)
        tool_args: Tool arguments (optional)
        source_content: Source content for tool handler (optional)
        additional_context: Additional context from context_scope.observe (optional).
                           Formatted and appended to prompt before LLM invocation.
        original_context: Original untransformed context for guards/debug (optional).
                         Tools and LLMs use the same transformed context_data_str.

    Returns:
        List of response items from the LLM
    """
    # IMPORTANT: formatted_prompt MUST be prepared using PromptPreparationService
    # before calling create_dynamic_agent(). This ensures:
    # - Static data loading (context_scope.static_data)
    # - Field reference replacement ({action.field}, {static.field})
    # - Context scope transformations (observe/drop/passthrough)
    # - Few-shot sample injection
    # - Consistent behavior across batch and realtime modes
    if formatted_prompt is None:
        raise ValueError(
            "formatted_prompt is required. "
            "Please use PromptPreparationService.prepare_prompt_with_context() "
            "to prepare the prompt before calling create_dynamic_agent(). "
            "See agent_actions/prompt_generation/data_generator.py for an example."
        )

    # Dispatch already handled by PromptPreparationService
    prompt_config = formatted_prompt

    # Setup tools_path for sys.path (still needed for function imports)
    if not tools_path:
        from agent_actions.utilities.tools_resolver import resolve_tools_path

        tools_path = resolve_tools_path(agent_config)
    if tools_path and tools_path not in sys.path:
        sys.path.insert(0, tools_path)

    # Get model vendor and check if tool
    model_vendor = (agent_config.get(MODEL_VENDOR_KEY) or "").lower()
    is_tool = model_vendor == "tool"

    # Prepare context data (critical: preserve context separation)
    context_data = ContextService.prepare_context_data(context_data_str, original_context, is_tool)

    # Note: dispatch_task() injection now happens in PromptPreparationService
    # TODO: captured_results (add_dispatch feature) needs to be returned from PromptPreparationService
    captured_results = {}

    # Append additional_context if provided (context_scope.observe fields)
    if additional_context:
        from agent_actions.utilities.context_scope.context_scope_processor import (
            ContextScopeProcessor,
        )

        context_msg = ContextScopeProcessor.format_llm_context(additional_context)
        if context_msg:
            prompt_config = f"{prompt_config}\n\n{context_msg}"

    # Prepare schema with dispatch support
    schema, schema_results = SchemaService.prepare_schema(
        agent_config, model_vendor, tools_path=tools_path, context_data=context_data
    )

    if schema_results:
        captured_results.update(schema_results)

    # Debug print
    PromptService.debug_print_prompt(
        agent_config,
        prompt_config,
        (
            context_data
            if isinstance(context_data, str)
            else json.dumps(context_data, ensure_ascii=False)
        ),
        schema,
    )

    # Get granularity
    granularity = (agent_config.get("granularity") or "record").lower()

    # Invoke client
    result = ClientInvocationService.invoke_client(
        model_vendor,
        agent_config,
        prompt_config,
        context_data,
        schema,
        granularity,
        formatted_prompt,
        tool_args,
        source_content,
    )

    # Merge captured results if any
    if captured_results:
        for item in result:
            if isinstance(item, dict):
                item.update(captured_results)

    return result
