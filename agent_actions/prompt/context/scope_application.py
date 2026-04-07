"""Context scope application and LLM context formatting."""

import json
import logging
from copy import deepcopy

from agent_actions.errors import ConfigurationError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.io_events import (
    ContextFieldSkippedEvent,
    ContextScopeAppliedEvent,
)
from agent_actions.prompt.context.scope_parsing import (
    extract_action_fields,
    extract_field_value,
    parse_field_reference,
)

logger = logging.getLogger(__name__)

# Sentinel distinguishing "field not found" from a field whose value is falsy (0, "", False, None).
_MISSING = object()

# Framework-injected namespaces that are always available for template rendering
# regardless of context_scope.observe/passthrough. These are not user data —
# they are iteration context, static reference data, and workflow metadata.
# Source: build_field_context_with_history() in scope_builder.py
FRAMEWORK_NAMESPACES = frozenset({"version", "seed", "workflow", "loop"})

__all__ = [
    "apply_context_scope",
    "format_llm_context",
    "merge_passthrough_fields",
]


def apply_context_scope(
    field_context: dict,
    context_scope: dict,
    static_data: dict | None = None,
    action_name: str = "unknown",
) -> tuple[dict, dict, dict]:
    """
    Apply context_scope rules, returning (prompt_context, llm_context, passthrough_fields).

    Adds SEED namespace from static_data parameter (namespace #3 per anatomy_action.md).
    This is the 5th namespace that gets added to field_context before filtering.

    Args:
        field_context: Input context with {source, {dep_name}, version, workflow} namespaces
        context_scope: Dict with observe/passthrough/drop lists
        static_data: Optional seed data to add under 'seed' namespace
        action_name: Name of the action for event logging

    Returns:
        Tuple of (prompt_context, llm_context, passthrough_fields)
    """
    # Deep copy to avoid mutating original field_context
    prompt_context = deepcopy(field_context)
    llm_context = {}
    passthrough_fields = {}

    # Process STATIC_DATA: Add SEED namespace (namespace #3)
    if static_data:
        logger.debug("[STATIC_DATA] Merging %s static data fields into context", len(static_data))
        logger.debug("[STATIC_DATA] Fields: %s", list(static_data.keys()))

        # Add under 'seed' namespace in prompt_context (for field reference replacement)
        # This allows references like {{seed.exam_syllabus}} in prompts
        if "seed" in prompt_context:
            logger.warning(
                "Seed data namespace 'seed' conflicts with existing action. "
                "Seed data will overwrite it."
            )
        prompt_context["seed"] = static_data
        logger.debug("[SEED_DATA] Added to prompt_context under 'seed' namespace")

    # Process DROP: Remove from prompt_context (security)
    drop_refs = context_scope.get("drop", [])
    for field_ref in drop_refs:
        try:
            ns_name, field_name = parse_field_reference(field_ref)

            # Remove from prompt_context
            if field_name == "_":
                # Version prefix pattern — checked before ns existence since
                # the base name won't exist, only versioned names do.
                matched = False
                for ctx_ns in prompt_context:
                    if ctx_ns.startswith(f"{ns_name}_") and isinstance(
                        prompt_context[ctx_ns], dict
                    ):
                        prompt_context[ctx_ns].clear()
                        matched = True
                if not matched:
                    logger.warning(
                        "Drop directive '%s' in action '%s' matched zero fields — "
                        "no namespaces matching prefix '%s_' found in context.",
                        field_ref,
                        action_name,
                        ns_name,
                    )
            elif ns_name not in prompt_context:
                logger.warning(
                    "Drop directive '%s' in action '%s' matched zero fields — "
                    "namespace '%s' not found in context.",
                    field_ref,
                    action_name,
                    ns_name,
                )
            elif not isinstance(prompt_context[ns_name], dict):
                logger.warning(
                    "Drop directive '%s' in action '%s' matched zero fields — "
                    "namespace '%s' is not a dict (got %s).",
                    field_ref,
                    action_name,
                    ns_name,
                    type(prompt_context[ns_name]).__name__,
                )
            elif field_name == "*":
                # Wildcard: clear entire namespace
                if not prompt_context[ns_name]:
                    logger.warning(
                        "Drop directive '%s' in action '%s' matched zero fields — "
                        "namespace '%s' is empty.",
                        field_ref,
                        action_name,
                        ns_name,
                    )
                prompt_context[ns_name].clear()
            else:
                # Exact field: warn if absent
                if field_name not in prompt_context[ns_name]:
                    logger.warning(
                        "Drop directive '%s' in action '%s' matched zero fields — "
                        "field '%s' not found in namespace '%s'.",
                        field_ref,
                        action_name,
                        field_name,
                        ns_name,
                    )
                prompt_context[ns_name].pop(field_name, None)

        except ValueError as e:
            logger.warning(
                "Drop directive failed to parse field reference '%s' in action '%s': %s. "
                "Field will NOT be removed — review context_scope.drop configuration.",
                field_ref,
                action_name,
                e,
            )
            fire_event(
                ContextFieldSkippedEvent(
                    action_name=action_name,
                    field_ref=field_ref,
                    reason=str(e),
                    directive="drop",
                )
            )
            continue

    # Process OBSERVE: Extract to llm_context, KEEP in prompt_context for template rendering
    observe_refs = context_scope.get("observe", [])
    for field_ref in observe_refs:
        try:
            ns_name, field_name = parse_field_reference(field_ref)

            if field_name == "*":
                # Wildcard: best-effort — namespace may be empty or absent.
                # This is intentionally lenient: explicit field refs (dep.field)
                # fail-fast, but wildcards (dep.*) are "give me what you have".
                action_fields = extract_action_fields(prompt_context, ns_name)
                if action_fields:
                    llm_context.update(action_fields)
            elif field_name == "_":
                # Version prefix pattern — best-effort like wildcard.
                for ctx_ns in prompt_context:
                    if ctx_ns.startswith(f"{ns_name}_"):
                        action_fields = extract_action_fields(prompt_context, ctx_ns)
                        if action_fields:
                            llm_context.update(action_fields)
            else:
                # Explicit field ref: fail-fast if not found
                value = extract_field_value(prompt_context, ns_name, field_name, default=_MISSING)

                if value is _MISSING:
                    raise ConfigurationError(
                        f"context_scope.observe field '{field_ref}' not found at runtime",
                        context={
                            "action": action_name,
                            "field_ref": field_ref,
                            "directive": "observe",
                            "operation": "apply_context_scope",
                            "hint": f"Field '{field_name}' does not exist in '{ns_name}' output. "
                            f"Check the output schema of '{ns_name}'.",
                        },
                    )

                # Add to llm_context (flat dict with field names as keys)
                llm_context[field_name] = value

                # DO NOT remove from prompt_context - users need it for {{action.field}} template refs

        except ValueError as e:
            fire_event(
                ContextFieldSkippedEvent(
                    action_name=action_name,
                    field_ref=field_ref,
                    reason=str(e),
                    directive="observe",
                )
            )
            continue

    # Process PASSTHROUGH: Extract to passthrough_fields, remove from prompt_context
    passthrough_refs = context_scope.get("passthrough", [])
    for field_ref in passthrough_refs:
        try:
            ns_name, field_name = parse_field_reference(field_ref)

            if field_name == "*":
                action_fields = extract_action_fields(field_context, ns_name)
                if action_fields:
                    passthrough_fields.update(action_fields)
            elif field_name == "_":
                for ctx_ns in field_context:
                    if ctx_ns.startswith(f"{ns_name}_"):
                        action_fields = extract_action_fields(field_context, ctx_ns)
                        if action_fields:
                            passthrough_fields.update(action_fields)
            else:
                # Extract value from original field_context
                value = extract_field_value(field_context, ns_name, field_name, default=_MISSING)

                if value is _MISSING:
                    raise ConfigurationError(
                        f"context_scope.passthrough field '{field_ref}' not found at runtime",
                        context={
                            "action": action_name,
                            "field_ref": field_ref,
                            "directive": "passthrough",
                            "operation": "apply_context_scope",
                            "hint": f"Field '{field_name}' does not exist in '{ns_name}' output. "
                            f"Check the output schema of '{ns_name}'.",
                        },
                    )

                # Add to passthrough_fields (flat dict with field names as keys)
                passthrough_fields[field_name] = value

        except ValueError as e:
            fire_event(
                ContextFieldSkippedEvent(
                    action_name=action_name,
                    field_ref=field_ref,
                    reason=str(e),
                    directive="passthrough",
                )
            )
            continue

    # Gate prompt_context to scoped fields only.
    # Only fields declared in observe or passthrough (plus framework namespaces)
    # are accessible for Jinja2 template rendering.
    allowed: dict[str, set[str] | str] = {}
    for field_ref in observe_refs + passthrough_refs:
        try:
            ns_name, field_name = parse_field_reference(field_ref)
        except ValueError:
            continue
        if field_name == "_":
            # Field prefix pattern: allow all matching version namespaces
            for ctx_ns in prompt_context:
                if ctx_ns.startswith(f"{ns_name}_"):
                    allowed[ctx_ns] = "*"
        elif field_name == "*":
            allowed[ns_name] = "*"
        else:
            if ns_name not in allowed:
                allowed[ns_name] = set()
            current = allowed[ns_name]
            if isinstance(current, set):
                current.add(field_name)

    filtered: dict = {}
    for ns, data in prompt_context.items():
        if ns in FRAMEWORK_NAMESPACES:
            filtered[ns] = data
        elif ns in allowed:
            if allowed[ns] == "*" or not isinstance(data, dict):
                filtered[ns] = data
            else:
                filtered[ns] = {k: v for k, v in data.items() if k in allowed[ns]}

    excluded = set(prompt_context.keys()) - set(filtered.keys())
    if excluded:
        logger.debug(
            "[CONTEXT_GATE] Action '%s': excluded namespaces from prompt_context: %s",
            action_name,
            sorted(excluded),
        )
    prompt_context = filtered

    # Fire event for scope application
    fire_event(
        ContextScopeAppliedEvent(
            action_name=action_name,
            observe_count=len(observe_refs),
            passthrough_count=len(passthrough_refs),
            drop_count=len(drop_refs),
            observe_fields=observe_refs,
            passthrough_fields=passthrough_refs,
            drop_fields=drop_refs,
        )
    )

    return (prompt_context, llm_context, passthrough_fields)


def format_llm_context(llm_context: dict) -> str:
    """Format llm_context dict as readable text for LLM message injection."""
    if not llm_context:
        return ""

    lines = ["Additional context:"]

    for key, value in llm_context.items():
        # Format value as pretty JSON for readability
        value_str = json.dumps(value, indent=2, ensure_ascii=False)
        lines.append(f"{key}: {value_str}")

    return "\n".join(lines)


def merge_passthrough_fields(llm_response: list[dict], passthrough_fields: dict) -> list[dict]:
    """Merge passthrough fields into LLM response.

    Returns a new structure -- the caller's original is never mutated.
    """
    if not passthrough_fields:
        return llm_response

    # Handle list of items
    result = []
    for item in llm_response:
        if isinstance(item, dict):
            item_copy = dict(item)
            if "content" in item_copy and isinstance(item_copy["content"], dict):
                item_copy["content"] = {**item_copy["content"], **passthrough_fields}
            else:
                item_copy.update(passthrough_fields)
            result.append(item_copy)
        else:
            result.append(item)  # type: ignore[unreachable]
    return result
