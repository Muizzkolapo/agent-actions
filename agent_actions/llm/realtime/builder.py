"""Agent builder module for dynamic LLM agent invocation.

This module provides the main entry point for creating and executing dynamic agents
with support for multiple LLM vendors.
"""

import json
from pathlib import Path
from typing import Any

from agent_actions.output.response.schema import ResponseSchemaCompiler
from agent_actions.utils.constants import MODEL_VENDOR_KEY

from .services import (
    ClientInvocationService,
    ContextService,
    PromptService,
)


def create_dynamic_agent(
    agent_config: dict[str, Any],
    udf: Any,
    context_data_str: str | dict,
    formatted_prompt: str | None = None,
    tools_path: str | None = None,
    tool_args: dict[str, Any] | None = None,
    source_content: Any | None = None,
    additional_context: dict | None = None,
) -> list[Any]:
    """Build and execute a prompt against the selected vendor.

    Args:
        agent_config: Agent configuration with model/prompt settings.
        udf: User defined function (agent_name).
        context_data_str: Context data for LLM (may be transformed with
            context_scope.drop applied).
        formatted_prompt: Pre-formatted prompt (optional, from DataGenerator).
        tools_path: Path to tool functions (optional).
        tool_args: Tool arguments (optional).
        source_content: Source content for tool handler (optional).
        additional_context: Additional context from context_scope.observe (optional).
            Formatted and appended to prompt before LLM invocation.

    Returns:
        List of response items from the LLM.
    """
    # IMPORTANT: formatted_prompt MUST be prepared using PromptPreparationService
    # before calling create_dynamic_agent(). This ensures:
    # - Static data loading (context_scope.static_data)
    # - Field reference replacement ({action.field}, {static.field})
    # - Context scope transformations (observe/drop/passthrough)
    # - Few-shot sample injection
    # - Consistent behavior across batch and online modes
    if formatted_prompt is None:
        raise ValueError(
            "formatted_prompt is required. "
            "Please use PromptPreparationService.prepare_prompt_with_context() "
            "to prepare the prompt before calling create_dynamic_agent(). "
            "See agent_actions/prompt_generation/data_generator.py for an example."
        )

    # Dispatch already handled by PromptPreparationService
    prompt_config = formatted_prompt

    if not tools_path:
        from agent_actions.utils.tools_resolver import resolve_tools_path

        tools_path = resolve_tools_path(agent_config)

    model_vendor = (agent_config.get(MODEL_VENDOR_KEY) or "").lower()
    is_tool = model_vendor == "tool"

    # Prepare context data (critical: preserve context separation)
    context_data = ContextService.prepare_context_data(context_data_str, is_tool)

    # Note: dispatch_task() injection now happens in PromptPreparationService
    captured_results = {}

    # Append additional_context if provided (context_scope.observe fields)
    if additional_context:
        from agent_actions.prompt.context.scope_application import format_llm_context

        context_msg = format_llm_context(additional_context)
        if context_msg:
            prompt_config = f"{prompt_config}\n\n{context_msg}"

    # Prepare schema with dispatch support
    _pr = agent_config.get("_project_root")
    compiler = ResponseSchemaCompiler(
        project_root=Path(_pr) if _pr else None,
        tools_path=tools_path,
    )
    schema, schema_results = compiler.compile(agent_config, model_vendor, context_data)

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
        schema,  # type: ignore[arg-type]
    )

    granularity = (agent_config.get("granularity") or "record").lower()

    # Invoke client
    result = ClientInvocationService.invoke_client(
        model_vendor,
        agent_config,
        prompt_config,
        context_data,
        schema,  # type: ignore[arg-type]
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
