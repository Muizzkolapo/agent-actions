"""
Context Scope Normalizer - Centralized normalization for context_scope directives.

Handles:
- Directive registry (list vs dict directives)
- Version reference expansion (action.* -> action_)
- Preserves both raw and expanded versions
"""

from typing import Dict, Any, List, Optional
from copy import deepcopy
import logging

logger = logging.getLogger(__name__)

# Directive registry: distinguishes how each directive type should be handled
DIRECTIVE_REGISTRY = {
    # List directives - contain field references to expand
    "observe": {"type": "list", "expand_versions": True},
    "passthrough": {"type": "list", "expand_versions": True},
    "drop": {"type": "list", "expand_versions": True},
    "drops": {"type": "list", "expand_versions": True},
    # Dict directives - preserve as-is (never expand)
    "seed_data": {"type": "dict", "expand_versions": False},
}


def normalize_context_scope(
    context_scope: Optional[Dict[str, Any]],
    version_base_map: Dict[str, List[str]],
) -> Optional[Dict[str, Any]]:
    """
    Normalize context_scope by expanding version references in list directives only.

    Args:
        context_scope: Raw context_scope from config
        version_base_map: Mapping of version base names to expanded agent names
                       e.g., {"extract_raw_qa": ["extract_raw_qa_1", "extract_raw_qa_2"]}

    Returns:
        Normalized context_scope with version references expanded in list directives,
        dict directives preserved as-is.
    """
    if not context_scope:
        return context_scope

    expanded_scope = {}

    for directive_name, directive_value in context_scope.items():
        directive_info = DIRECTIVE_REGISTRY.get(
            directive_name, {"type": "unknown", "expand_versions": False}
        )

        if directive_info["type"] == "list" and directive_info["expand_versions"]:
            # List directive - expand version references
            if isinstance(directive_value, list):
                expanded_scope[directive_name] = _expand_list_directive(
                    directive_value, version_base_map
                )
            else:
                expanded_scope[directive_name] = directive_value
        else:
            # Dict directive or unknown - preserve as-is
            # Note: Using deepcopy to avoid shared references between raw and expanded.
            # For large seed_data dicts, this has a performance cost, but ensures safety.
            # Could optimize to shallow copy if values are guaranteed immutable.
            expanded_scope[directive_name] = deepcopy(directive_value)

    return expanded_scope


def _expand_list_directive(
    field_refs: List[str],
    version_base_map: Dict[str, List[str]],
) -> List[str]:
    """
    Expand version base name references in a list of field references.

    Converts wildcard references like "extract_raw_qa.*" to field prefix
    patterns like "extract_raw_qa_" which match all version iteration fields.

    Field Prefix Pattern Convention:
    --------------------------------
    A trailing underscore WITHOUT a dot indicates a field prefix pattern.

    Examples:
    - "extract_raw_qa.*"  -> "extract_raw_qa_"   (matches all fields from version iterations)
    - "extract_raw_qa_1_questions", "extract_raw_qa_2_questions", etc.

    The trailing underscore is detected by context_scope_processor.py:368-379
    using the pattern: field_ref.endswith("_") and "." not in field_ref

    This convention allows efficient field matching without regex overhead.
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

        if action_name in version_base_map:
            if field_name == "*":
                # Wildcard: "extract_raw_qa.*" -> "extract_raw_qa_"
                expanded_refs.append(f"{action_name}_")
            else:
                # Specific field reference - keep as-is
                expanded_refs.append(field_ref)
        else:
            # Not a version base name - keep as-is
            expanded_refs.append(field_ref)

    return expanded_refs


def normalize_all_agent_configs(
    agent_configs: Dict[str, Dict[str, Any]],
    execution_order: List[str],
) -> None:
    """
    Normalize context_scope for all agents, adding context_scope_expanded field.

    MUTATION CONTRACT:
    ------------------
    This function mutates agent_configs IN PLACE by adding 'context_scope_expanded'
    to each agent that has a context_scope. The original 'context_scope' field is
    preserved and NOT mutated.

    This is part of the config normalization pipeline:
    1. ConfigManager.determine_execution_order() calls this function
    2. ActionLevelOrchestrator.compute_execution_levels() expands dependencies
    3. Both stages mutate agent_configs as part of config bootstrapping

    Args:
        agent_configs: Dictionary of agent configurations (WILL BE MUTATED)
        execution_order: List of agent names in topological order
    """
    # Build version base name map
    version_base_map = _build_version_base_name_map(agent_configs, execution_order)

    for agent_name in execution_order:
        config = agent_configs.get(agent_name, {})
        context_scope = config.get("context_scope")

        if context_scope:
            # Create expanded version
            expanded = normalize_context_scope(context_scope, version_base_map)
            config["context_scope_expanded"] = expanded

            logger.debug(
                "Normalized context_scope for '%s': raw=%s, expanded=%s",
                agent_name,
                context_scope.keys(),
                expanded.keys() if expanded else None,
            )


def _build_version_base_name_map(
    agent_configs: Dict[str, Dict[str, Any]],
    execution_order: List[str],
) -> Dict[str, List[str]]:
    """Build mapping from version base names to their expanded agent names."""
    version_base_map: Dict[str, List[str]] = {}

    for agent_name in execution_order:
        config = agent_configs.get(agent_name, {})
        if config.get("is_versioned_agent"):
            base_name = config.get("version_base_name")
            if base_name:
                if base_name not in version_base_map:
                    version_base_map[base_name] = []
                version_base_map[base_name].append(agent_name)

    return version_base_map
