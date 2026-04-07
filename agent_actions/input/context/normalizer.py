"""Centralized normalization for context_scope directives."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Directive registry: distinguishes how each directive type should be handled
DIRECTIVE_REGISTRY = {
    # List directives - contain field references to expand
    "observe": {"type": "list", "expand_versions": True},
    "passthrough": {"type": "list", "expand_versions": True},
    "drop": {"type": "list", "expand_versions": True},
    "drops": {"type": "list", "expand_versions": True},
    # Dict directives - preserve as-is (never expand)
    "seed_path": {"type": "dict", "expand_versions": False},
}

# Config keys that users confuse with the runtime 'seed' namespace in references.
SEED_CONFIG_KEYS = frozenset({"seed_data", "seed_path"})


def normalize_context_scope(
    context_scope: dict[str, Any] | None,
    version_base_map: dict[str, list[str]],
) -> dict[str, Any] | None:
    """Expand version references in list directives, preserving dict directives as-is."""
    if not context_scope:
        return context_scope

    expanded_scope = {}

    for directive_name, directive_value in context_scope.items():
        directive_info = DIRECTIVE_REGISTRY.get(
            directive_name, {"type": "unknown", "expand_versions": False}
        )

        if directive_info["type"] == "list" and directive_info["expand_versions"]:
            if isinstance(directive_value, list):
                expanded_scope[directive_name] = _expand_list_directive(
                    directive_value, version_base_map
                )
            else:
                expanded_scope[directive_name] = directive_value
        else:
            expanded_scope[directive_name] = directive_value

    return expanded_scope


def _expand_list_directive(
    field_refs: list[str],
    version_base_map: dict[str, list[str]],
) -> list[str]:
    """Expand version base name references to concrete versioned references.

    Any reference targeting a version base name gets expanded to one reference
    per version variant. Both wildcards and specific fields are expanded:
      "action.*"     → ["action_1.*", "action_2.*", "action_3.*"]
      "action.score" → ["action_1.score", "action_2.score", "action_3.score"]
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
            for variant in version_base_map[action_name]:
                expanded_refs.append(f"{variant}.{field_name}")
        else:
            expanded_refs.append(field_ref)

    return expanded_refs


def normalize_all_agent_configs(
    agent_configs: dict[str, dict[str, Any]],
) -> None:
    """Normalize context_scope for all agents in-place.

    MUTATION CONTRACT: mutates agent_configs IN PLACE by replacing each agent's
    'context_scope' with its normalized form (version base name references
    expanded to concrete versioned references).
    """
    version_base_map = _build_version_base_name_map(agent_configs)

    for agent_name, config in agent_configs.items():
        context_scope = config.get("context_scope")

        if context_scope:
            expanded = normalize_context_scope(context_scope, version_base_map)
            config["context_scope"] = expanded

            logger.debug(
                "Normalized context_scope for '%s': %s",
                agent_name,
                expanded.keys() if expanded else None,
            )


def _build_version_base_name_map(
    agent_configs: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Build mapping from version base names to their expanded agent names."""
    version_base_map: dict[str, list[str]] = {}

    for agent_name, config in agent_configs.items():
        if config.get("is_versioned_agent"):
            base_name = config.get("version_base_name")
            if base_name:
                if base_name not in version_base_map:
                    version_base_map[base_name] = []
                version_base_map[base_name].append(agent_name)

    return version_base_map
