"""Config merge and initialization functions extracted from ActionExpander."""

from typing import Any

from agent_actions.output.response.config_fields import get_default


def merge_directive_value(existing: Any, new_value: Any) -> Any:
    """Merge two directive values based on their types."""
    if isinstance(existing, dict) and isinstance(new_value, dict):
        return {**existing, **new_value}
    if isinstance(existing, list) and isinstance(new_value, list):
        return list(dict.fromkeys(existing + new_value))
    return new_value


def deep_merge_context_scope(
    defaults_scope: dict[str, Any] | None, action_scope: dict[str, Any] | None
) -> dict[str, Any]:
    """
    Deep merge context_scope directives from defaults and action levels.

    Action-level directives are merged with (not replace) defaults directives.
    This allows actions to define drop/observe while inheriting seed_path from defaults.
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
    agent: dict[str, Any], action: dict[str, Any], defaults: dict[str, Any]
) -> None:
    """Process chunk configuration for an agent."""
    chunk_config = action.get("chunk_config", defaults.get("chunk_config", {}))
    if chunk_config:
        agent["chunk_config"] = chunk_config
    else:
        agent["chunk_config"] = {}
        if action.get("chunk_size") or defaults.get("chunk_size"):
            agent["chunk_config"]["chunk_size"] = action.get(
                "chunk_size", defaults.get("chunk_size", get_default("chunk_size"))
            )
        if action.get("chunk_overlap") or defaults.get("chunk_overlap"):
            agent["chunk_config"]["chunk_overlap"] = action.get(
                "chunk_overlap", defaults.get("chunk_overlap", get_default("chunk_overlap"))
            )


def initialize_optional_fields(agent: dict[str, Any]) -> None:
    """Initialize optional fields in agent configuration."""
    agent.setdefault("skip_if", None)
    agent.setdefault("add_dispatch", None)
    agent.setdefault("conditional_clause", None)
    agent.setdefault("guard", None)
