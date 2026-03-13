"""Context scope application and LLM context formatting."""

import json
import logging
from copy import deepcopy

from agent_actions.logging import fire_event
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
            if ns_name in prompt_context and isinstance(prompt_context[ns_name], dict):
                prompt_context[ns_name].pop(field_name, None)

        except ValueError as e:
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
                action_fields = extract_action_fields(field_context, ns_name)
                if action_fields:
                    llm_context.update(action_fields)
            else:
                # Extract value from original field_context (before drop removed it)
                value = extract_field_value(field_context, ns_name, field_name)

                if value is not None:
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
            else:
                # Extract value from original field_context
                value = extract_field_value(field_context, ns_name, field_name)

                if value is not None:
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
    if isinstance(llm_response, list):
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
                result.append(item)
        return result

    # Handle single dict
    if isinstance(llm_response, dict):
        result = dict(llm_response)
        if "content" in result and isinstance(result["content"], dict):
            result["content"] = {**result["content"], **passthrough_fields}
        else:
            result.update(passthrough_fields)
        return result

    # Other types (shouldn't happen, but be defensive)
    return llm_response
