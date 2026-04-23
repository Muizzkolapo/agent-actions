"""Namespace enrichment and field filtering."""

import logging
from typing import Any

from agent_actions.errors import ConfigurationError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.io_events import ContextFieldSkippedEvent
from agent_actions.prompt.context.scope_parsing import parse_field_reference
from agent_actions.utils.dict import get_nested_value, nested_field_exists, set_nested_value

logger = logging.getLogger(__name__)

# System/metadata keys excluded from content extraction.
# These are infrastructure fields that must not leak into downstream prompts.
_RECORD_METADATA_KEYS = frozenset(
    {
        "source_guid",
        "lineage",
        "node_id",
        "metadata",
        "target_id",
        "parent_target_id",
        "root_target_id",
        "chunk_info",
        "_recovery",
        "_unprocessed",
    }
)

__all__: list[str] = []


def _extract_content_data(source_content: Any) -> dict:
    """
    Extract content portion from record structure.

    Handles both:
    - {source_guid, content: {...}} wrapper -> extract content
    - Flat dict -> return as-is (excluding metadata keys)
    """
    if not isinstance(source_content, dict):
        return {}

    # Wrapped format: {source_guid, content: {...}}
    if "content" in source_content and isinstance(source_content["content"], dict):
        return source_content["content"]

    # Flat format: {...} but exclude metadata keys
    return {k: v for k, v in source_content.items() if k not in _RECORD_METADATA_KEYS}


def _enrich_source_namespace(
    base_namespace: dict[str, Any], current_item: dict[str, Any] | None
) -> dict[str, Any]:
    """
    Merge fallback fields into the source namespace from the current item.

    This helps downstream actions get at least one source-like namespace even if the
    stored source file was sparse (e.g., only identifiers).
    """
    merged = dict(base_namespace or {})

    if not current_item or not isinstance(current_item, dict):
        return merged

    fallback = _extract_content_data(current_item)
    for key, value in fallback.items():
        if key not in merged:
            merged[key] = value

    return merged


def _filter_and_store_fields(
    field_context: dict,
    name: str,
    data: dict,
    allowed_fields: list[str] | None,
    source_type: str = "FIELD",
    fail_on_missing: bool = False,
    metadata_collector: dict | None = None,
) -> None:
    """
    Filter data by allowed_fields and store in field_context.

    Args:
        field_context: Target dict to store filtered data
        name: Key name for storing in field_context
        data: Source data to filter
        allowed_fields: Fields to include (None = wildcard, all fields)
        source_type: Log prefix for debug messages (e.g., "INPUT SOURCE")
        fail_on_missing: If True, raise ConfigurationError when declared fields are missing
        metadata_collector: Optional dict to record stored vs loaded field metadata.
            When provided, records {name: {stored_fields, loaded_fields, stored_count, loaded_count}}
            for downstream diagnostics (e.g. detecting fields produced by tools but not in schema).
    """
    stored_fields = set(data.keys())

    if allowed_fields is None:
        # Wildcard: Load all fields
        field_context[name] = data
        logger.debug(
            "[%s] Loaded '%s' with ALL %d fields (wildcard)",
            source_type,
            name,
            len(data),
        )
        if metadata_collector is not None:
            metadata_collector[name] = {
                "stored_fields": sorted(stored_fields),
                "loaded_fields": sorted(stored_fields),
                "stored_count": len(stored_fields),
                "loaded_count": len(stored_fields),
            }
    else:
        # Specific fields: Filter
        filtered_data = {}
        for field in allowed_fields:
            if field in data:
                # Exact key match (flat field or literal dotted key)
                filtered_data[field] = data[field]
            elif "." in field:
                # Nested path: extract only the declared subfield
                if nested_field_exists(data, field):
                    set_nested_value(filtered_data, field, get_nested_value(data, field))
        if fail_on_missing:
            missing_fields = set()
            for field in allowed_fields:
                if field in data:
                    continue
                if "." in field and field.split(".")[0] in data:
                    continue
                missing_fields.add(field)
            if missing_fields:
                raise ConfigurationError(
                    f"[{source_type}] '{name}': declared fields {sorted(missing_fields)} "
                    f"not found. Available: {list(data.keys())}",
                    context={
                        "source_type": source_type,
                        "name": name,
                        "missing_fields": sorted(missing_fields),
                        "available_fields": list(data.keys()),
                        "operation": "filter_and_store_fields",
                    },
                )
        field_context[name] = filtered_data
        logger.debug(
            "[%s] Loaded '%s' with %d fields: %s",
            source_type,
            name,
            len(filtered_data),
            list(filtered_data.keys()),
        )
        if metadata_collector is not None:
            loaded_fields = sorted(filtered_data.keys())
            metadata_collector[name] = {
                "stored_fields": sorted(stored_fields),
                "loaded_fields": loaded_fields,
                "stored_count": len(stored_fields),
                "loaded_count": len(loaded_fields),
            }


def _extract_allowed_fields_per_dependency(
    dependencies: list[str], context_scope: dict | None, action_name: str = "unknown"
) -> dict[str, list[str] | None]:
    """
    Extract which fields are allowed for each dependency from context_scope.

    Returns dict mapping dependency name to:
    - None: Wildcard (all fields allowed)
    - List[str]: Specific field names allowed
    - Empty list: No fields declared (shouldn't happen, but defensive)

    Example:
        context_scope = {
            "observe": ["add_answer_text.*", "classify.question_type"],
            "passthrough": ["add_answer_text.question"]
        }
        dependencies = ["add_answer_text", "classify"]

        Returns:
        {
            "add_answer_text": None,  # Wildcard
            "classify": ["question_type"]  # Specific field
        }
    """
    if not context_scope:
        if dependencies:
            raise ConfigurationError(
                f"Action '{action_name}' has dependencies but no context_scope defined. "
                f"All dependencies must have explicit field declarations.\n\n"
                f"Dependencies: {dependencies}",
                context={"action": action_name, "dependencies": dependencies},
            )
        return {}

    allowed_per_dep: dict[str, list[str] | None] = {}

    # Collect field references from observe and passthrough
    # (both need to be loaded into field_context)
    all_field_refs = []
    all_field_refs.extend(context_scope.get("observe", []))
    all_field_refs.extend(context_scope.get("passthrough", []))

    declared_deps = set()

    for field_ref in all_field_refs:
        try:
            ref_action, ref_field = parse_field_reference(field_ref)
            declared_deps.add(ref_action)
        except ValueError as e:
            fire_event(
                ContextFieldSkippedEvent(
                    action_name=action_name,
                    field_ref=field_ref,
                    reason=str(e),
                    directive="extract_allowed_fields",
                )
            )
            continue

    for dep_name in dependencies:
        wildcard_found = False
        specific_fields = []

        for field_ref in all_field_refs:
            try:
                ref_action, ref_field = parse_field_reference(field_ref)

                if ref_action != dep_name:
                    continue

                if ref_field == "*":
                    wildcard_found = True
                    break
                else:
                    specific_fields.append(ref_field)

            except ValueError as e:
                fire_event(
                    ContextFieldSkippedEvent(
                        action_name=action_name,
                        field_ref=field_ref,
                        reason=str(e),
                        directive="extract_allowed_fields_inner",
                    )
                )
                continue

        if wildcard_found:
            allowed_per_dep[dep_name] = None  # All fields
        elif specific_fields:
            allowed_per_dep[dep_name] = list(set(specific_fields))  # Deduplicate
        else:
            # Dependency declared but no fields referenced in context_scope
            # This is now an error (no implicit field loading)
            raise ConfigurationError(
                f"Dependency '{dep_name}' declared but not referenced in context_scope. "
                f"Add field declarations (e.g., '{dep_name}.*' or '{dep_name}.field_name').\n\n"
                f"All dependencies: {dependencies}\n"
                f"Declared in context_scope: {list(declared_deps)}",
                context={
                    "action": action_name,
                    "missing_dependency": dep_name,
                    "all_dependencies": dependencies,
                    "declared_dependencies": list(declared_deps),
                },
            )

    return allowed_per_dep
