"""Field reference parsing and action name extraction utilities."""

import re

from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.io_events import ContextFieldSkippedEvent
from agent_actions.utils.constants import SPECIAL_NAMESPACES

__all__ = [
    "parse_field_reference",
    "extract_field_names_from_references",
    "extract_action_names_from_context_scope",
    "extract_action_names_from_template",
    "extract_field_value",
    "extract_action_fields",
]


def parse_field_reference(field_ref: str) -> tuple[str, str]:
    """
    Parse field reference in 'action.field' format, returning (action_name, field_name).

    Also handles loop field prefix patterns (e.g., 'extract_raw_qa_') which indicate
    fields from all loop iterations. For these patterns, returns (base_name, '_')
    where '_' signals a field prefix pattern.
    """
    if not field_ref or not isinstance(field_ref, str):
        raise ValueError(
            f"Invalid field reference: {field_ref!r}. "
            f"Expected non-empty string in format 'action.field' or field prefix pattern ending with '_'"
        )

    # Check if this is a field prefix pattern (ends with _ but no dot)
    # e.g., "extract_raw_qa_" for loop consumption
    if field_ref.endswith("_") and "." not in field_ref:
        # Field prefix pattern - return base name and '_' marker
        base_name = field_ref[:-1]  # Remove trailing underscore
        if not base_name:
            raise ValueError(
                f"Invalid field prefix pattern: '{field_ref}'. Base name cannot be empty"
            )
        return (base_name, "_")

    parts = field_ref.split(".", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Invalid field reference: '{field_ref}'. "
            f"Expected format: 'action.field' (with exactly one dot) or field prefix pattern ending with '_'"
        )

    action_name, field_name = parts

    if not action_name or not field_name:
        raise ValueError(
            f"Invalid field reference: '{field_ref}'. Both action and field must be non-empty"
        )

    return (action_name, field_name)


def extract_field_names_from_references(
    field_refs: list[str], _return_type: str = "list"
) -> list[str]:
    """
    Extract field names from list of field references.

    Args:
        field_refs: List of references in 'action.field' format
        _return_type: Return type ('list' or other - currently only 'list' supported)

    Returns:
        List of field names extracted from references

    Example:
        ['generate_summary.key_concepts', 'extract.facts'] -> ['key_concepts', 'facts']
    """
    field_names = []

    for field_ref in field_refs:
        try:
            _, field_name = parse_field_reference(field_ref)
            field_names.append(field_name)
        except ValueError as e:
            fire_event(
                ContextFieldSkippedEvent(
                    action_name="unknown",
                    field_ref=field_ref,
                    reason=str(e),
                    directive="extract_field_names",
                )
            )
            continue

    return field_names


def extract_action_names_from_context_scope(context_scope: dict | None) -> set:
    """
    Extract unique action names referenced in context_scope.

    Parses observe and passthrough fields to find all action names.

    Args:
        context_scope: Context scope configuration dict

    Returns:
        Set of action names referenced in context_scope

    Example:
        context_scope = {
            "observe": ["add_answer_text.*", "suggest_distractor_counts.target_word_counts"],
            "passthrough": ["write_scenario_question.question"]
        }
        Returns: {"add_answer_text", "suggest_distractor_counts", "write_scenario_question"}
    """
    if not context_scope:
        return set()

    referenced_actions = set()

    # Collect field references from observe and passthrough
    all_field_refs = []
    all_field_refs.extend(context_scope.get("observe", []))
    all_field_refs.extend(context_scope.get("passthrough", []))

    for field_ref in all_field_refs:
        try:
            action_name, _ = parse_field_reference(field_ref)
            referenced_actions.add(action_name)
        except ValueError as e:
            fire_event(
                ContextFieldSkippedEvent(
                    action_name="unknown",
                    field_ref=field_ref,
                    reason=str(e),
                    directive="extract_action_names",
                )
            )
            continue

    return referenced_actions


def extract_action_names_from_template(template: str | None) -> set:
    """
    Extract unique action names referenced in a Jinja2 template.

    Parses template for {{ namespace.field }} patterns and extracts namespace names.
    Filters out special namespaces (source, version, workflow) and common Jinja2 filters.

    Args:
        template: Jinja2 template string

    Returns:
        Set of action names (potential upstream dependencies) referenced in template

    Example:
        template = "{{ summarize_page_content.summary }} and {{ source.text }}"
        Returns: {"summarize_page_content"}  # 'source' is filtered as special namespace
    """
    if not template or not isinstance(template, str):
        return set()

    referenced_actions = set()

    # Match {{ namespace.field }} or {{ namespace['field'] }} patterns
    # This regex captures the namespace (first identifier before . or [)
    pattern = r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*[\.\[]"
    matches = re.findall(pattern, template)

    for namespace in matches:
        # Filter out special namespaces and common Jinja2 variables
        if namespace in SPECIAL_NAMESPACES:
            continue
        if namespace in ("loop", "range", "true", "false", "none", "self", "version"):
            continue
        referenced_actions.add(namespace)

    return referenced_actions


def extract_field_value(field_context: dict, action_name: str, field_name: str, default=None):
    """Extract field value from nested field_context structure, returning default if not found."""
    from agent_actions.utils.dict import get_nested_value

    if not isinstance(field_context, dict):
        return default  # type: ignore[unreachable]

    if action_name not in field_context:
        return default

    action_data = field_context[action_name]

    if not isinstance(action_data, dict):
        return default

    # Exact key match first (backward compat for flat fields and literal dotted keys)
    if field_name in action_data:
        return action_data[field_name]

    # Nested path traversal for dot-separated paths
    if "." in field_name:
        return get_nested_value(action_data, field_name, default=default)

    return default


def extract_action_fields(field_context: dict, action_name: str) -> dict | None:
    """Return all fields for an action if present and dict-like, otherwise None."""
    if not isinstance(field_context, dict):
        return None  # type: ignore[unreachable]

    action_data = field_context.get(action_name)
    if not isinstance(action_data, dict):
        return None

    return action_data
