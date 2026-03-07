"""Config merge and initialization functions extracted from ActionExpander."""

from typing import Dict, Any, Optional

from agent_actions.config.types import AgentEntryDict


def merge_directive_value(existing: Any, new_value: Any) -> Any:
    """Merge two directive values based on their types."""
    if isinstance(existing, dict) and isinstance(new_value, dict):
        return {**existing, **new_value}
    if isinstance(existing, list) and isinstance(new_value, list):
        return list(dict.fromkeys(existing + new_value))
    return new_value


def deep_merge_context_scope(
    defaults_scope: Optional[Dict[str, Any]], action_scope: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Deep merge context_scope directives from defaults and action levels.

    Action-level directives are merged with (not replace) defaults directives.
    This allows actions to define drop/observe while inheriting seed_data from defaults.
    """
    if not defaults_scope:
        return action_scope or {}
    if not action_scope:
        return defaults_scope or {}

    merged = {**defaults_scope}

    for key, value in action_scope.items():
        if key in merged:
            merged[key] = merge_directive_value(merged[key], value)
        else:
            merged[key] = value

    return merged


def process_chunk_config(
    agent: AgentEntryDict, action: Dict[str, Any], defaults: Dict[str, Any]
) -> None:
    """Process chunk configuration for an agent."""
    chunk_config = action.get("chunk_config", defaults.get("chunk_config", {}))
    if chunk_config:
        agent["chunk_config"] = chunk_config
    else:
        agent["chunk_config"] = {}
        if action.get("chunk_size") or defaults.get("chunk_size"):
            agent["chunk_config"]["chunk_size"] = action.get(
                "chunk_size", defaults.get("chunk_size", 300)
            )
        if action.get("chunk_overlap") or defaults.get("chunk_overlap"):
            agent["chunk_config"]["chunk_overlap"] = action.get(
                "chunk_overlap", defaults.get("chunk_overlap", 10)
            )


def initialize_optional_fields(agent: AgentEntryDict) -> None:
    """Initialize optional fields in agent configuration."""
    agent["skip_if"] = None
    agent["ephemeral"] = None
    agent["add_dispatch"] = None
    agent["anthropic_version"] = None
    agent["enable_prompt_caching"] = None
    if "conditional_clause" not in agent:
        agent["conditional_clause"] = None
    if "guard" not in agent:
        agent["guard"] = None
