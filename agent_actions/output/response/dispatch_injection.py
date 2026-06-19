"""
Dispatch and injection logic for schema processing.

Handles recursive dispatch_task() resolution and injection into schema structures.
"""

import logging
from typing import Any

from agent_actions.errors import ConfigValidationError

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

    Raises:
        ConfigValidationError: If dispatch_task() resolution fails. Letting the
            unresolved string flow to the LLM vendor produces opaque API errors
            (or malformed output for permissive vendors); failing here surfaces
            the misconfiguration at compile time with a clear error.
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
    if isinstance(schema, str) and "dispatch_task(" in schema:
        from agent_actions.prompt.prompt_utils import PromptUtils

        try:
            return PromptUtils.process_dispatch_in_text(
                schema,
                tools_path=tools_path or "",
                context_data_str=context_data_str or "",
                agent_config=agent_config,
                captured_results=captured_results,
                preserve_type_on_exact_match=True,
            )
        except Exception as e:
            raise ConfigValidationError(
                f"dispatch_task() resolution failed in schema: {e}. "
                "Check that the referenced UDF exists under tools/<workflow>/ and "
                "that its signature matches the dispatch_task() call.",
                context={
                    "schema_fragment": schema,
                    "tools_path": tools_path,
                    "error_type": type(e).__name__,
                },
            ) from e
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
        Resolved schema (unchanged if it is not a dispatch_task string).

    Raises:
        ConfigValidationError: If dispatch_task() resolution fails. Same reasoning
            as ``_inject_functions_into_schema``: silent fallback was masking
            broken configs and producing opaque downstream API errors.
    """
    if not isinstance(schema, str) or "dispatch_task(" not in schema:
        return schema

    from agent_actions.prompt.prompt_utils import PromptUtils

    try:
        return PromptUtils.process_dispatch_in_text(
            schema,
            tools_path=tools_path or "",
            context_data_str=context_data_str,
            agent_config=agent_config,
            captured_results=captured_results,
            preserve_type_on_exact_match=True,
        )
    except Exception as e:
        raise ConfigValidationError(
            f"dispatch_task() resolution failed in schema: {e}. "
            "Check that the referenced UDF exists under tools/<workflow>/ and "
            "that its signature matches the dispatch_task() call.",
            context={
                "schema_fragment": schema,
                "tools_path": tools_path,
                "error_type": type(e).__name__,
            },
        ) from e
