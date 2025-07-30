"""Utility helpers shared across processors."""
from __future__ import annotations
from typing import Any, Dict, Optional

from agent_actions.core.tooling import execute_user_defined_function
from agent_actions.models import agent_builder
from agent_actions.transformers.data_transformer import DataTransformer
from agent_actions.constants import SIDE_COLLECTION_KEY
from .processor_utils import ProcessorUtils


def apply_remove_collection(contents: Any, agent_config: Dict) -> Any:
    """Apply ``remove_collection`` transformations consistently."""
    return ProcessorUtils.apply_remove_collection(contents, agent_config)


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
        return context, False

    # Apply remove_collection only after conditional check passes
    processed_context = apply_remove_collection(context, agent_config)

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


def transform_with_side_collection(
    data: list,
    context_data: dict,
    source_guid: str,
    agent_config: Dict,
    idx: int = 0,
) -> list:
    """Apply ``side_collection`` logic to generated data consistently."""
    return ProcessorUtils.transform_with_side_collection(
        data, context_data, source_guid, agent_config, idx
    )

