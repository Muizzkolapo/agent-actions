"""
Dispatch and injection logic for schema processing.

Handles recursive dispatch_task() resolution and injection into schema structures.
"""

import logging
from typing import Any

from agent_actions.errors import AgentActionsError

logger = logging.getLogger(__name__)


def _inject_functions_into_schema(
    schema: Any,
    tools_path: str | None,
    context_data_str: str | None,
    agent_config: dict[str, Any] | None,
    captured_results: dict[str, Any],
) -> Any:
    """
    Recursively traverse schema and replace dispatch_task() calls.

    Args:
        schema: The schema object (dict, list, or primitive)
        tools_path: Path to tools directory
        context_data_str: Context data for functions
        agent_config: Agent configuration
        captured_results: Dictionary to collect function outputs (add_dispatch)

    Returns:
        The processed schema with function outputs injected
    """
    if isinstance(schema, dict):
        return {
            k: _inject_functions_into_schema(
                v, tools_path, context_data_str, agent_config, captured_results
            )
            for k, v in schema.items()
        }
    if isinstance(schema, list):
        return [
            _inject_functions_into_schema(
                item, tools_path, context_data_str, agent_config, captured_results
            )
            for item in schema
        ]
    if isinstance(schema, str):
        if "dispatch_task(" in schema:
            try:
                from agent_actions.prompt.prompt_utils import PromptUtils

                return PromptUtils.process_dispatch_in_text(
                    schema,
                    tools_path=tools_path or "",
                    context_data_str=context_data_str or "",
                    agent_config=agent_config,
                    captured_results=captured_results,
                    preserve_type_on_exact_match=True,
                )
            except (ValueError, TypeError, KeyError, AgentActionsError) as e:
                logger.warning(
                    "dispatch_task resolution failed in schema — the unresolved string "
                    "will be passed to the LLM vendor as-is, which may cause API errors: %s",
                    e,
                )
                return schema
        return schema
    return schema


def _resolve_dispatch_in_schema(
    schema: Any,
    tools_path: str | None,
    context_data_str: str,
    agent_config: dict[str, Any],
    captured_results: dict[str, Any],
) -> Any:
    """
    Resolve dispatch_task calls in schema string.

    Args:
        schema: Schema value (may be string with dispatch_task)
        tools_path: Path to tools directory
        context_data_str: Context data as JSON string
        agent_config: Agent configuration
        captured_results: Dictionary to collect function outputs

    Returns:
        Resolved schema (original if not a dispatch call or resolution fails)
    """
    if not isinstance(schema, str) or "dispatch_task(" not in schema:
        return schema

    try:
        from agent_actions.prompt.prompt_utils import PromptUtils

        return PromptUtils.process_dispatch_in_text(
            schema,
            tools_path=tools_path or "",
            context_data_str=context_data_str,
            agent_config=agent_config,
            captured_results=captured_results,
            preserve_type_on_exact_match=True,
        )
    except (ValueError, TypeError, KeyError, AgentActionsError) as e:
        logger.warning(
            "dispatch_task resolution failed in schema — the unresolved string "
            "will be passed to the LLM vendor as-is, which may cause API errors: %s",
            e,
        )
        return schema
