"""Utility helpers shared across processors."""
from __future__ import annotations
import uuid
from typing import Any, Dict, Optional

from agent_actions.core.tooling import execute_user_defined_function
from agent_actions.models import agent_builder
from agent_actions.transformers.data_transformer import DataTransformer
from agent_actions.constants import SIDE_COLLECTION_KEY


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


def transform_with_side_collection(
    data: list,
    context_data: dict,
    source_guid: str,
    agent_config: Dict,
    idx: int = 0,
) -> list:
    """Apply ``side_collection`` logic to generated data consistently."""
    side_collection = agent_config.get(SIDE_COLLECTION_KEY, [])

    if side_collection:
        updated = [
            DataTransformer.update_schema_objects(context_data, item, side_collection)
            for item in data
        ]
        output = DataTransformer.transform_structure([{source_guid: updated}])
    else:
        output = data
    # Patch: Ensure every output object has target_id, source_guid, node_id
    for idx_obj, obj in enumerate(output):
        if 'target_id' not in obj or not obj['target_id']:
            obj['target_id'] = str(uuid.uuid4())
        if 'source_guid' not in obj or not obj['source_guid']:
            obj['source_guid'] = source_guid
        if 'node_id' not in obj or not obj['node_id']:
            obj['node_id'] = f"node_{idx}_{uuid.uuid4()}"
    return output

