"""Context scope application and LLM context formatting."""

import json
import logging
from collections import Counter
from copy import deepcopy
from typing import Any

from agent_actions.errors import ConfigurationError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.io_events import (
    ContextFieldSkippedEvent,
    ContextScopeAppliedEvent,
)
from agent_actions.prompt.context.scope_namespace import _extract_content_data
from agent_actions.prompt.context.scope_parsing import (
    extract_action_fields,
    extract_field_value,
    parse_field_reference,
)
from agent_actions.utils.content import get_existing_content

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
    "apply_context_scope_for_records",
    "format_llm_context",
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
    # Early return: no directive keys declared at all = pass everything through.
    # Distinct from {"observe": []} which means "gate to framework namespaces only".
    if (
        "observe" not in context_scope
        and "passthrough" not in context_scope
        and "drop" not in context_scope
    ):
        return (deepcopy(field_context), {}, {})

    # Deep copy to avoid mutating original field_context
    prompt_context = deepcopy(field_context)
    llm_context: dict[str, dict[str, Any]] = {}
    passthrough_fields: dict[str, dict[str, Any]] = {}

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

    # Process PASSTHROUGH first: extract from pre-drop prompt_context.
    # Drop is then applied to passthrough_fields explicitly below,
    # so the drop directive removes fields from both observe and output.
    passthrough_refs = context_scope.get("passthrough", [])
    for field_ref in passthrough_refs:
        try:
            ns_name, field_name = parse_field_reference(field_ref)

            if field_name == "*":
                action_fields = extract_action_fields(prompt_context, ns_name)
                if action_fields:
                    passthrough_fields.setdefault(ns_name, {}).update(action_fields)
            else:
                value = extract_field_value(prompt_context, ns_name, field_name, default=_MISSING)

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

                passthrough_fields.setdefault(ns_name, {})[field_name] = value

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

    # Process DROP: Remove from prompt_context (observe) and passthrough_fields (output)
    drop_refs = context_scope.get("drop", [])
    for field_ref in drop_refs:
        try:
            ns_name, field_name = parse_field_reference(field_ref)

            # Remove from prompt_context
            if ns_name not in prompt_context:
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
                if ns_name in passthrough_fields:
                    del passthrough_fields[ns_name]
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
                if ns_name in passthrough_fields:
                    passthrough_fields[ns_name].pop(field_name, None)
                    if not passthrough_fields[ns_name]:
                        del passthrough_fields[ns_name]

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
                action_fields = extract_action_fields(prompt_context, ns_name)
                if action_fields:
                    llm_context.setdefault(ns_name, {}).update(action_fields)
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

                llm_context.setdefault(ns_name, {})[field_name] = value

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

    # Gate prompt_context to scoped fields only.
    # Only fields declared in observe or passthrough (plus framework namespaces)
    # are accessible for Jinja2 template rendering.
    allowed: dict[str, set[str] | str] = {}
    for field_ref in observe_refs + passthrough_refs:
        try:
            ns_name, field_name = parse_field_reference(field_ref)
        except ValueError:
            continue
        if field_name == "*":
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
    """Format llm_context dict as readable text for LLM message injection.

    llm_context is namespaced: {action_name: {field: value, ...}, ...}.
    Each namespace is rendered as a labeled section.
    """
    if not llm_context:
        return ""

    lines = ["Additional context:"]

    for ns_name, ns_data in llm_context.items():
        for field, value in ns_data.items():
            value_str = json.dumps(value, indent=2, ensure_ascii=False)
            lines.append(f"{ns_name}.{field}: {value_str}")

    return "\n".join(lines)


# ── FILE mode helpers ──────────────────────────────────────────────────


def _build_source_index(source_data: list[dict] | None) -> dict[str | None, dict]:
    """Build source_guid -> source record index for cross-record source resolution."""
    index: dict[str | None, dict] = {}
    if not source_data:
        return index
    for src in source_data:
        sguid = src.get("source_guid") if isinstance(src, dict) else None
        if sguid:
            index[sguid] = src
    return index


def _resolve_source_content(
    source_guid: str | None,
    source_index: dict[str | None, dict],
    source_data: list[dict] | None,
) -> dict:
    """Resolve source namespace content for a record via source_guid.

    Falls back to first source record if source_guid not found in index.
    """
    matched = source_index.get(source_guid)
    if not matched and source_data:
        matched = source_data[0]
    if matched:
        return _extract_content_data(matched)
    return {}


def _resolve_observe_refs_for_flat_keys(
    observe_refs: list[str],
    action_name: str = "unknown",
) -> tuple[list[tuple[str, str, str]], bool]:
    """Parse observe refs and detect bare-key collisions for FILE mode flat key injection.

    Returns (resolved, qualify_wildcards) where resolved is a list of
    (namespace, field_name, output_key) triples. output_key is
    namespace-qualified when bare-key collisions are detected.
    qualify_wildcards is True when multiple wildcard namespaces exist.
    """
    valid_pairs: list[tuple[str, str]] = []

    for ref in observe_refs:
        try:
            ns, field = parse_field_reference(ref)
            valid_pairs.append((ns, field))
        except ValueError as e:
            fire_event(
                ContextFieldSkippedEvent(
                    action_name=action_name,
                    field_ref=ref,
                    reason=str(e),
                    directive="resolve_observe_refs",
                )
            )
            continue

    bare_counts = Counter(field for _, field in valid_pairs)
    collisions = {k for k, v in bare_counts.items() if v > 1}

    wildcard_ns: set[str] = set()
    resolved: list[tuple[str, str, str]] = []
    for ns, field in valid_pairs:
        if field == "*":
            wildcard_ns.add(ns)
        output_key = f"{ns}.{field}" if field in collisions else field
        resolved.append((ns, field, output_key))

    return resolved, len(wildcard_ns) > 1


def _apply_drops_to_content(content: dict, drop_refs: list[str]) -> None:
    """Apply drop directives to content dict in-place.

    Silently skips unparseable refs or missing namespaces.
    """
    for ref in drop_refs:
        try:
            ns, field = parse_field_reference(ref)
        except ValueError:
            continue
        if ns not in content or not isinstance(content[ns], dict):
            continue
        if field == "*":
            content[ns].clear()
        else:
            content[ns].pop(field, None)


def _inject_flat_observed_keys(
    content: dict,
    resolved_observe: list[tuple[str, str, str]],
    qualify_wildcards: bool,
) -> None:
    """Inject flat observed keys into content for FILE mode enrichment.

    Reads values from post-drop content namespaces and injects them as
    top-level keys. Wildcard refs expand to all fields in the namespace.
    Keys are namespace-qualified when collisions are detected.
    """
    for ns, field, output_key in resolved_observe:
        ns_data = content.get(ns)
        if not isinstance(ns_data, dict):
            continue

        if field == "*":
            for f, v in ns_data.items():
                key = f"{ns}.{f}" if qualify_wildcards else f
                content[key] = v
        elif field in ns_data:
            content[output_key] = ns_data[field]


# ── FILE mode wrapper ──────────────────────────────────────────────────


def apply_context_scope_for_records(
    records: list[dict],
    context_scope: dict,
    action_name: str = "unknown",
    source_data: list[dict] | None = None,
) -> list[dict]:
    """Apply context_scope to a list of records (FILE mode).

    For each record:
    1. Extract namespaced content
    2. Resolve source namespace via source_guid cross-reference
    3. Call apply_context_scope() for observe/drop/passthrough processing
    4. Rebuild enriched record: original content + drops applied + flat observed keys

    Unlike apply_context_scope() which gates prompt_context to observed namespaces
    only (correct for Jinja), this function preserves ALL original namespaces in the
    enriched record because downstream guards need full namespace visibility.
    """
    observe_refs = context_scope.get("observe", [])
    passthrough_refs = context_scope.get("passthrough", [])
    drop_refs = context_scope.get("drop", [])

    if not observe_refs and not passthrough_refs and not drop_refs:
        return records

    # Check if any directive references the source namespace
    all_refs = observe_refs + passthrough_refs + drop_refs
    has_source_refs = any(ref.startswith("source.") for ref in all_refs)

    source_index = _build_source_index(source_data) if has_source_refs else {}
    resolved_observe, qualify_wildcards = (
        _resolve_observe_refs_for_flat_keys(observe_refs, action_name)
        if observe_refs
        else ([], False)
    )

    source_cache: dict[str | None, dict] = {}
    enriched: list[dict] = []

    for record in records:
        content = get_existing_content(record)

        # Build field_context with source namespace resolved
        field_context = dict(content)
        if has_source_refs:
            sguid = record.get("source_guid")
            if sguid not in source_cache:
                source_cache[sguid] = _resolve_source_content(sguid, source_index, source_data)
            source_content = source_cache[sguid]
            if source_content:
                field_context["source"] = source_content

        # Call unified bus filter (validates refs, fires events)
        apply_context_scope(field_context, context_scope, action_name=action_name)

        # Rebuild enriched record: ALL namespaces preserved, drops applied, flat keys
        enriched_content = deepcopy(content)
        if has_source_refs and source_cache.get(record.get("source_guid")):
            enriched_content["source"] = deepcopy(source_cache[record.get("source_guid")])
        _apply_drops_to_content(enriched_content, drop_refs)
        _inject_flat_observed_keys(enriched_content, resolved_observe, qualify_wildcards)

        enriched.append({**record, "content": enriched_content})

    return enriched
