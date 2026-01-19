"""
Context Scope Normalizer - Centralized normalization for context_scope directives.

Handles:
- Directive registry (list vs dict directives)
- Loop reference expansion (action.* -> action_)
- Preserves both raw and expanded versions
"""

from typing import Dict, Any, List, Optional
from copy import deepcopy
import logging

logger = logging.getLogger(__name__)

# Directive registry: distinguishes how each directive type should be handled
DIRECTIVE_REGISTRY = {
    # List directives - contain field references to expand
    "observe": {"type": "list", "expand_loops": True},
    "passthrough": {"type": "list", "expand_loops": True},
    "drop": {"type": "list", "expand_loops": True},
    "drops": {"type": "list", "expand_loops": True},
    # Dict directives - preserve as-is (never expand)
    "seed_data": {"type": "dict", "expand_loops": False},
}


def normalize_context_scope(
    context_scope: Optional[Dict[str, Any]],
    loop_base_map: Dict[str, List[str]],
) -> Optional[Dict[str, Any]]:
    """
    Normalize context_scope by expanding loop references in list directives only.

    Args:
        context_scope: Raw context_scope from config
        loop_base_map: Mapping of loop base names to expanded agent names
                       e.g., {"extract_raw_qa": ["extract_raw_qa_1", "extract_raw_qa_2"]}

    Returns:
        Normalized context_scope with loop references expanded in list directives,
        dict directives preserved as-is.
    """
    if not context_scope:
        return context_scope

    expanded_scope = {}

    for directive_name, directive_value in context_scope.items():
        directive_info = DIRECTIVE_REGISTRY.get(
            directive_name, {"type": "unknown", "expand_loops": False}
        )

        if directive_info["type"] == "list" and directive_info["expand_loops"]:
            # List directive - expand loop references
            if isinstance(directive_value, list):
                expanded_scope[directive_name] = _expand_list_directive(
                    directive_value, loop_base_map
                )
            else:
                expanded_scope[directive_name] = directive_value
        else:
            # Dict directive or unknown - preserve as-is
            expanded_scope[directive_name] = deepcopy(directive_value)

    return expanded_scope


def _expand_list_directive(
    field_refs: List[str],
    loop_base_map: Dict[str, List[str]],
) -> List[str]:
    """
    Expand loop base name references in a list of field references.

    Converts wildcard references like "extract_raw_qa.*" to field prefix
    patterns like "extract_raw_qa_" which match all loop iteration fields.
    """
    expanded_refs = []

    for field_ref in field_refs:
        if not isinstance(field_ref, str) or "." not in field_ref:
            expanded_refs.append(field_ref)
            continue

        parts = field_ref.split(".", 1)
        if len(parts) != 2:
            expanded_refs.append(field_ref)
            continue

        action_name, field_name = parts

        if action_name in loop_base_map:
            if field_name == "*":
                # Wildcard: "extract_raw_qa.*" -> "extract_raw_qa_"
                expanded_refs.append(f"{action_name}_")
            else:
                # Specific field reference - keep as-is
                expanded_refs.append(field_ref)
        else:
            # Not a loop base name - keep as-is
            expanded_refs.append(field_ref)

    return expanded_refs


def normalize_all_agent_configs(
    agent_configs: Dict[str, Dict[str, Any]],
    execution_order: List[str],
) -> None:
    """
    Normalize context_scope for all agents, adding context_scope_expanded field.

    Mutates agent_configs in place by adding 'context_scope_expanded' to each agent
    that has a context_scope.

    Args:
        agent_configs: Dictionary of agent configurations
        execution_order: List of agent names in topological order
    """
    # Build loop base name map
    loop_base_map = _build_loop_base_name_map(agent_configs, execution_order)

    for agent_name in execution_order:
        config = agent_configs.get(agent_name, {})
        context_scope = config.get("context_scope")

        if context_scope:
            # Create expanded version
            expanded = normalize_context_scope(context_scope, loop_base_map)
            config["context_scope_expanded"] = expanded

            logger.debug(
                "Normalized context_scope for '%s': raw=%s, expanded=%s",
                agent_name,
                list(context_scope.keys()),
                list(expanded.keys()) if expanded else None,
            )


def _build_loop_base_name_map(
    agent_configs: Dict[str, Dict[str, Any]],
    execution_order: List[str],
) -> Dict[str, List[str]]:
    """Build mapping from loop base names to their expanded agent names."""
    loop_base_map: Dict[str, List[str]] = {}

    for agent_name in execution_order:
        config = agent_configs.get(agent_name, {})
        if config.get("is_loop_agent"):
            base_name = config.get("loop_base_name")
            if base_name:
                if base_name not in loop_base_map:
                    loop_base_map[base_name] = []
                loop_base_map[base_name].append(agent_name)

    return loop_base_map
