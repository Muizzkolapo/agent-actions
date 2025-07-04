"""Utility helpers shared across processors."""
from __future__ import annotations

from typing import Any, Dict, Optional

from agent_actions.core.tooling import execute_user_defined_function
from agent_actions.models import agent_builder
from agent_actions.transformers.data_transformer import DataTransformer


def apply_remove_collection(contents: Any, agent_config: Dict) -> Any:
    """Apply ``remove_collection`` transformations consistently."""
    remove_collection = agent_config.get("remove_collection", [])
    if remove_collection and isinstance(contents, dict):
        return DataTransformer.remove_schema_objects(contents, remove_collection)
    return contents


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
    """Execute an agent based on a conditional clause configuration.

    Returns a tuple of the response and a boolean indicating whether
    the agent was executed.
    """
    conditional_clause = agent_config.get("conditional_clause", "").lower()

    if conditional_clause and not execute_user_defined_function(
        conditional_clause, context
    ):
        return [context], False

    response = agent_builder.create_dynamic_agent(
        agent_config,
        agent_name,
        context,
        formatted_prompt,
        tools_path=tools_path,
        tool_args=tool_args,
        source_content=source_content,
    )
    return response, True
