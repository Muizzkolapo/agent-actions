"""Centralized normalization for context_scope directives."""

import logging
from typing import Any

from agent_actions.errors import ConfigurationError

logger = logging.getLogger(__name__)

# Directive registry: distinguishes how each directive type should be handled
DIRECTIVE_REGISTRY = {
    # List directives - contain field references to expand
    "observe": {"type": "list", "expand_versions": True},
    "passthrough": {"type": "list", "expand_versions": True},
    "drop": {"type": "list", "expand_versions": True},
    # Dict directives - preserve as-is (never expand)
    "seed": {"type": "dict", "expand_versions": False},
}

# Not a directive a workflow writes: split_optional_observe keeps each optional observe
# reference here, with the value a record lacking the field is given.
OPTIONAL_DIRECTIVE = "optional"
_OPTIONAL_MARK = "?"
_OPTIONAL_ENTRY_KEYS = ("field", "optional", "default")

# An action's searches of a knowledge base; the load turns each entry into a step.
RETRIEVE_DIRECTIVE = "retrieve"

# Namespaces users write in prompt references when they mean the 'seed' namespace.
SEED_CONFIG_KEYS = frozenset({"seed_data", "seed_path", "static_data"})


def normalize_context_scope(
    context_scope: dict[str, Any] | None,
    version_base_map: dict[str, list[str]],
) -> dict[str, Any]:
    """Normalize and expand version references in context_scope.

    Guarantees a dict return — null or non-dict input becomes {}.
    Null list directives (observe: null from YAML) become [].
    """
    if not context_scope or not isinstance(context_scope, dict):
        return {}

    expanded_scope: dict[str, Any] = {}

    for directive_name, directive_value in split_optional_observe(context_scope).items():
        if directive_name == OPTIONAL_DIRECTIVE:
            # Keyed by reference, so a version base name expands as it does in observe.
            expanded_scope[directive_name] = {
                expanded_ref: default
                for ref, default in directive_value.items()
                for expanded_ref in _expand_list_directive([ref], version_base_map)
            }
            continue
        if directive_name == RETRIEVE_DIRECTIVE:
            # The load turns an action's own entries into steps; any left came from defaults.
            raise ConfigurationError(
                "context_scope.retrieve is set on the action that reads it, not under "
                "'defaults:' or 'default_agent_config:'.",
                context={"directive": directive_name},
            )
        if directive_name not in DIRECTIVE_REGISTRY:
            raise ConfigurationError(
                f"context_scope.{directive_name} is not a valid directive. "
                f"Valid directives: {', '.join(sorted(DIRECTIVE_REGISTRY))}.",
                context={
                    "directive": directive_name,
                    "valid_directives": sorted(DIRECTIVE_REGISTRY),
                },
            )
        directive_info = DIRECTIVE_REGISTRY[directive_name]

        if directive_info["type"] == "list" and directive_info["expand_versions"]:
            if isinstance(directive_value, list):
                expanded_scope[directive_name] = _expand_list_directive(
                    directive_value, version_base_map
                )
            else:
                # Null or wrong type → normalize to empty list
                expanded_scope[directive_name] = []
        else:
            expanded_scope[directive_name] = directive_value

    # Again on the expanded names: 'ext.x?' becomes 'ext_1.x', which a drop of 'ext_1.*' removes.
    _refuse_dropped_optional(
        expanded_scope.get(OPTIONAL_DIRECTIVE, {}), expanded_scope.get("drop")
    )
    return expanded_scope


def split_optional_observe(context_scope: Any) -> Any:
    """*context_scope* with every observe entry a plain reference.

    An optional entry (``a.b?``, or ``{field: a.b, optional: true, default: x}``) leaves
    ``a.b`` in ``observe`` and ``a.b: x`` under ``optional``, the one place its being
    optional is read from. Returns *context_scope* itself when it is already so, or is
    no mapping at all.
    """
    if not isinstance(context_scope, dict):
        return context_scope
    for directive in ("passthrough", "drop"):
        entries = context_scope.get(directive)
        for entry in entries if isinstance(entries, list) else []:
            if _is_optional_form(entry):
                raise ConfigurationError(
                    f"context_scope.{directive} entry {_shown(entry)} is written as optional, "
                    "which only an observe entry can be. Write the plain reference "
                    "('action.field').",
                    context={"directive": directive, "entry": _shown(entry)},
                )

    stated = context_scope.get(OPTIONAL_DIRECTIVE)
    if stated is not None and not isinstance(stated, dict):
        raise hand_written_optional_error()
    entries = context_scope.get("observe")
    if not isinstance(entries, list) or all(
        isinstance(entry, str) and _OPTIONAL_MARK not in entry for entry in entries
    ):
        _refuse_dropped_optional(stated or {}, context_scope.get("drop"))
        return context_scope

    references: list[Any] = []
    optional: dict[str, Any] = dict(stated or {})
    for entry in entries:
        if not isinstance(entry, str | dict):
            references.append(entry)
            continue
        reference, is_optional, default = _read_observe_entry(entry)
        if is_optional and (default is not None or reference not in optional):
            optional[reference] = default
        if reference not in references:
            references.append(reference)

    _refuse_dropped_optional(optional, context_scope.get("drop"))
    split = {**context_scope, "observe": references}
    if optional:
        split[OPTIONAL_DIRECTIVE] = optional
    return split


def _refuse_dropped_optional(optional: dict[str, Any], drop: Any) -> None:
    """Drop runs before observe, so the field would never be read: only its default."""
    if not isinstance(drop, list):
        return
    for ref in optional:
        namespace = ref.split(".", 1)[0]
        match = next(
            (
                d
                for d in drop
                if isinstance(d, str) and (d in (ref, f"{namespace}.*") or ref.startswith(f"{d}."))
            ),
            None,
        )
        if match is None:
            continue
        raise ConfigurationError(
            f"context_scope.observe entry '{ref}?' is optional, and the drop entry '{match}' "
            "removes the same field, so every record would get the default. Remove the drop "
            "entry to read the field, or the observe entry to withhold it.",
            context={"directive": "observe", "entry": f"{ref}?"},
        )


def hand_written_optional_error() -> ConfigurationError:
    return ConfigurationError(
        "context_scope.optional is not written by hand. Mark the observe entry instead: "
        "'action.field?' or {field: action.field, optional: true}.",
        context={"directive": OPTIONAL_DIRECTIVE},
    )


def observe_entry_reference(entry: Any) -> str | None:
    """The plain reference an observe entry names, or None; refuses nothing."""
    if isinstance(entry, dict):
        entry = entry.get("field")
    if not isinstance(entry, str):
        return None
    return entry.strip().removesuffix(_OPTIONAL_MARK)


def _is_optional_form(entry: Any) -> bool:
    if isinstance(entry, dict):
        return any(key in entry for key in _OPTIONAL_ENTRY_KEYS)
    return isinstance(entry, str) and entry.strip().endswith(_OPTIONAL_MARK)


def _shown(entry: Any) -> str:
    return f"'{entry}'" if isinstance(entry, str) else str(entry)


def _read_observe_entry(entry: str | dict[str, Any]) -> tuple[str, bool, Any]:
    """(plain reference, whether it is optional, value when missing) of one observe entry."""

    def refuse(problem: str) -> ConfigurationError:
        return ConfigurationError(
            f"context_scope.observe entry {_shown(entry)}: {problem}",
            context={"directive": "observe", "entry": _shown(entry)},
        )

    written: Any = entry
    stated: bool | None = None
    default: Any = None
    if isinstance(entry, dict):
        unknown = sorted(str(key) for key in entry if key not in _OPTIONAL_ENTRY_KEYS)
        if unknown:
            raise refuse(
                f"unknown key {', '.join(unknown)}. An observe entry is a reference "
                f"('action.field') or a mapping of {', '.join(_OPTIONAL_ENTRY_KEYS)}."
            )
        written = entry.get("field")
        if not isinstance(written, str) or not written.strip():
            raise refuse("'field' must name the reference, as in {field: action.field}.")
        stated = entry.get("optional")
        if stated is not None and not isinstance(stated, bool):
            raise refuse("'optional' must be true or false.")
        default = entry.get("default")

    reference = written.strip()
    marked = reference.endswith(_OPTIONAL_MARK)
    if marked:
        reference = reference[: -len(_OPTIONAL_MARK)]
    if _OPTIONAL_MARK in reference:
        raise refuse(
            "'?' marks the whole entry optional and goes once, at the end of the "
            "reference ('action.field?')."
        )
    if stated is False and (marked or (isinstance(entry, dict) and "default" in entry)):
        raise refuse("'optional: false' contradicts the '?' or the 'default' beside it.")
    is_optional = marked or bool(stated) or (isinstance(entry, dict) and "default" in entry)
    if is_optional and reference.endswith(".*"):
        raise refuse(
            "a wildcard cannot be optional. It already resolves to whichever fields the "
            "record has; remove the optional form."
        )
    return reference, is_optional, default


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
        raw = config.get("context_scope")

        # Normalize: null → {}, non-dict → {}, expand version refs.
        # normalize_context_scope guarantees a dict return.
        expanded = normalize_context_scope(raw, version_base_map)
        config["context_scope"] = expanded

        if expanded:
            logger.debug(
                "Normalized context_scope for '%s': %s",
                agent_name,
                list(expanded.keys()),
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
