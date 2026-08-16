"""Context scope application and LLM context formatting."""

import json
import logging
from collections import Counter
from copy import deepcopy
from typing import Any

from agent_actions.errors import ConfigurationError, RecordContextError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.io_events import (
    ContextFieldSkippedEvent,
    ContextScopeAppliedEvent,
)
from agent_actions.prompt.context.null_namespace import is_null_namespace
from agent_actions.prompt.context.scope_namespace import _extract_content_data
from agent_actions.prompt.context.scope_parsing import (
    extract_action_fields,
    extract_field_value,
    parse_field_reference,
)
from agent_actions.record.reasons import OBSERVE_FIELD_MISSING, SOURCE_UNRESOLVED
from agent_actions.utils.constants import RUNTIME_BUS_NAMESPACES
from agent_actions.utils.content import get_existing_content

logger = logging.getLogger(__name__)

# Sentinel distinguishing "field not found" from a field whose value is falsy (0, "", False, None).
_MISSING = object()


def _resolve_missing_field(
    prompt_context: dict,
    ns_name: str,
    field_ref: str,
    action_name: str,
    directive: str,
) -> None:
    """Handle a missing field reference during scope application.

    Three cases:
    1. Namespace is null (NullNamespace sentinel or legacy None) → return None
    2. Namespace exists as dict but field is missing:
       - observe → raise RecordContextError (prevents None injection into prompts)
       - passthrough/drop → return None (match guard semantics)
    3. Namespace not in prompt_context at all → raise (config bug / typo)
    """
    if ns_name in prompt_context and is_null_namespace(prompt_context[ns_name]):
        logger.debug(
            "[%s NULL-SAFE] '%s' on action '%s': namespace '%s' is "
            "null (guard-skipped/filtered), resolving field as None",
            directive.upper(),
            field_ref,
            action_name,
            ns_name,
        )
        return None

    if ns_name in prompt_context and isinstance(prompt_context[ns_name], dict):
        if directive == "observe":
            raise RecordContextError(
                f"context_scope.observe field '{field_ref}' not found in namespace '{ns_name}'",
                context={
                    "action": action_name,
                    "field_ref": field_ref,
                    "directive": directive,
                    "operation": "apply_context_scope",
                    "hint": f"Namespace '{ns_name}' exists but field is missing. "
                    f"Upstream action may have produced incomplete output.",
                },
            )
        logger.warning(
            "[%s NULL-SAFE] '%s' on action '%s': field not found in namespace '%s', "
            "resolving as None to match guard semantics",
            directive.upper(),
            field_ref,
            action_name,
            ns_name,
        )
        return None

    raise RecordContextError(
        f"context_scope.{directive} field '{field_ref}' not found at runtime",
        context={
            "action": action_name,
            "field_ref": field_ref,
            "directive": directive,
            "operation": "apply_context_scope",
            "hint": f"Namespace '{ns_name}' not found in field_context. "
            f"Check the dependency graph for '{action_name}'.",
        },
    )


# Framework-injected namespaces that are always available for template rendering
# regardless of context_scope.observe/passthrough. These are not user data —
# they are iteration context, static reference data, and workflow metadata.
# Source: build_field_context_with_history() in scope_builder.py
FRAMEWORK_NAMESPACES = frozenset({"version", "seed", "workflow", "loop"})

# Field schemas for the fixed-shape framework namespaces. Single source of truth
# used by (1) runtime population (build_workflow_metadata below), (2) inspect
# context preview, and (3) any future static field-existence checks. `seed`,
# `source`, and `loop` are user-shaped and therefore not listed here.
FRAMEWORK_FIELDS: dict[str, tuple[str, ...]] = {
    "workflow": ("name", "run_id"),
    "version": ("i", "idx", "length", "first", "last"),
}


def build_workflow_metadata(name: str, run_id: str | None = None) -> dict[str, Any]:
    """Runtime workflow namespace matching FRAMEWORK_FIELDS['workflow'].

    `run_id` is None before a run is registered (e.g. batch prep) — the key is
    still emitted so `{{ workflow.run_id }}` renders as an empty string rather
    than raising TemplateVariableError."""
    return {"name": name, "run_id": run_id or ""}


__all__ = [
    "apply_context_scope",
    "apply_context_scope_for_records",
    "plan_flat_observed_keys",
    "format_llm_context",
    "FRAMEWORK_NAMESPACES",
    "FRAMEWORK_FIELDS",
    "build_workflow_metadata",
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

        # 'seed' is reserved for static data injection (SPECIAL_NAMESPACES blocks it upstream too).
        if "seed" in prompt_context:
            raise ConfigurationError(
                "Namespace collision: action named 'seed' conflicts with the seed data namespace. "
                "Rename the action to avoid overwriting its output with static seed data.",
                context={
                    "action_name": action_name,
                    "conflicting_namespace": "seed",
                },
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
                    _resolve_missing_field(
                        prompt_context, ns_name, field_ref, action_name, "passthrough"
                    )
                    value = None

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
                logger.debug(
                    "Drop directive '%s' in action '%s' matched zero fields — "
                    "namespace '%s' not found in context.",
                    field_ref,
                    action_name,
                    ns_name,
                )
            elif not isinstance(prompt_context[ns_name], dict):
                logger.debug(
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
                    logger.debug(
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
                    logger.debug(
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
                    _resolve_missing_field(
                        prompt_context, ns_name, field_ref, action_name, "observe"
                    )
                    value = None

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
    parent_source_guid: str | None = None,
) -> dict | None:
    """Resolve source namespace content for a record by identity.

    Tries the record's own source_guid, then its carried parent_source_guid
    (the original pool identity, preserved when expansion re-mints guids).
    A miss on both against a non-empty pool returns None — substituting any
    other record's source would attribute the wrong document, so the caller
    must skip the record instead.
    """
    matched = source_index.get(source_guid)
    if not matched and parent_source_guid:
        matched = source_index.get(parent_source_guid)
    if not matched and source_data:
        return None
    if matched:
        content = _extract_content_data(matched)
        # First-stage records nest the user payload under content.source; return that so
        # source.<field> resolves to the user field, not {"source": {...}}. Online source
        # records are flat (no "source" key) and pass through unchanged.
        source = content.get("source")
        if isinstance(source, dict):
            return source
        return content
    return {}


def _resolve_observe_refs_for_flat_keys(
    observe_refs: list[str],
    action_name: str = "unknown",
    *,
    emit_diagnostics: bool = True,
) -> tuple[list[tuple[str, str, str]], bool]:
    """Parse observe refs and detect bare-key collisions for FILE mode flat key injection.

    Returns (resolved, qualify_wildcards): (namespace, field_name, output_key)
    triples with output_key namespace-qualified on collision, and whether
    multiple wildcard namespaces exist. ``emit_diagnostics=False`` is for
    per-record callers re-resolving refs the enrichment pass already diagnosed.
    """
    valid_pairs: list[tuple[str, str]] = []

    for ref in observe_refs:
        try:
            ns, field = parse_field_reference(ref)
            valid_pairs.append((ns, field))
        except ValueError as e:
            if emit_diagnostics:
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

    if collisions and emit_diagnostics:
        qualified = sorted(f"{ns}.{field}" for ns, field in valid_pairs if field in collisions)
        logger.warning(
            "Action '%s': observe refs share bare field name(s) %s across namespaces. "
            "Flat keys are namespace-qualified (%s) — an action reading the bare key "
            "will not find it; read the qualified key instead.",
            action_name,
            sorted(collisions),
            ", ".join(qualified),
        )

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


def _expand_observed_fields(
    content: dict,
    resolved_observe: list[tuple[str, str, str]],
    qualify_wildcards: bool,
) -> list[tuple[str, str, str, Any, bool]]:
    """(namespace, field, declared key, value, came-from-wildcard) per observed field."""
    expanded: list[tuple[str, str, str, Any, bool]] = []
    for ns, field, output_key in resolved_observe:
        ns_data = content.get(ns)
        if not isinstance(ns_data, dict):
            continue
        if field == "*":
            expanded.extend(
                (ns, f, f"{ns}.{f}" if qualify_wildcards else f, v, True)
                for f, v in ns_data.items()
            )
        elif field in ns_data:
            expanded.append((ns, field, output_key, ns_data[field], False))
    return expanded


def plan_flat_observed_keys(
    content: dict,
    resolved_observe: list[tuple[str, str, str]],
    qualify_wildcards: bool,
    *,
    reserved_names: frozenset[str] | set[str] = frozenset(),
    action_name: str = "unknown",
) -> tuple[dict[str, Any], set[str]]:
    """Map observed fields to the flat keys FILE mode delivers them under.

    Every rule reads the observe refs, never the data, so a ref always produces
    the same key — on every record, batch and run. Deciding from the values
    would let a UDF's keys depend on which records share a file, which is the
    same silent loss as the overwrite this prevents.

    A key is qualified when delivering it bare could lose data: it names a
    namespace the action reads by that name, or a wildcard on another namespace
    could expand onto it. *reserved_names* is the extra protection a caller
    writing into a live record needs — applied, never announced, since the
    payload is a flat dict where that name is free.
    """
    declared_reserved = {ns for ns, _, _ in resolved_observe} | RUNTIME_BUS_NAMESPACES
    wildcard_namespaces = {ns for ns, field, _ in resolved_observe if field == "*"}

    flat: dict[str, Any] = {}
    announced: set[str] = set()
    for ns, field, key, value, from_wildcard in _expand_observed_fields(
        content, resolved_observe, qualify_wildcards
    ):
        qualified = f"{ns}.{field}"
        if key != qualified:
            if key in declared_reserved:
                key = qualified
                announced.add(key)
            elif not from_wildcard and wildcard_namespaces - {ns}:
                # A wildcard elsewhere may expand onto this bare name. Which
                # fields it actually yields is a property of the data, so the
                # only stable answer is to qualify whenever it is possible.
                key = qualified
                announced.add(key)
            elif key in reserved_names:
                key = qualified
        if key in flat and flat[key] is not value:
            # Only reachable when a field name literally contains a dot and
            # collides with another namespace's qualified key.
            logger.warning(
                "Action '%s': observed field '%s.%s' cannot be delivered — key '%s' is "
                "already taken by another observed field. Rename the field or observe "
                "fewer namespaces.",
                action_name,
                ns,
                field,
                key,
            )
            continue
        flat[key] = value

    return flat, announced


def _inject_flat_observed_keys(
    content: dict,
    resolved_observe: list[tuple[str, str, str]],
    qualify_wildcards: bool,
    action_name: str,
    reserved_namespaces: frozenset[str],
) -> set[str]:
    """Inject flat observed keys into post-drop content for FILE mode enrichment.

    *reserved_namespaces* is the union of namespace names across the batch (see
    caller): a flat key must never be written over a namespace, and reserving
    only this record's own namespaces would let the same ref qualify on one
    record and stay bare on the next, purely because of which namespace an
    unrelated upstream branch happened to populate for that record.
    """
    flat, announced = plan_flat_observed_keys(
        content,
        resolved_observe,
        qualify_wildcards,
        reserved_names=reserved_namespaces,
        action_name=action_name,
    )
    content.update(flat)
    return announced


# ── FILE mode wrapper ──────────────────────────────────────────────────


def apply_context_scope_for_records(
    records: list[dict],
    context_scope: dict,
    action_name: str = "unknown",
    source_data: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Apply context_scope to a list of records (FILE mode).

    For each record:
    1. Extract namespaced content
    2. Resolve source namespace via source_guid cross-reference
    3. Call apply_context_scope() for observe/drop/passthrough processing
    4. Rebuild enriched record: original content + drops applied + flat observed keys

    Unlike apply_context_scope() which gates prompt_context to observed namespaces
    only (correct for Jinja), this function preserves ALL original namespaces in the
    enriched record because downstream guards need full namespace visibility.

    Returns (enriched_records, skipped_records); skipped entries carry
    ``{"source_guid": ..., "reason": OBSERVE_FIELD_MISSING | SOURCE_UNRESOLVED}``.
    """
    observe_refs = context_scope.get("observe", [])
    passthrough_refs = context_scope.get("passthrough", [])
    drop_refs = context_scope.get("drop", [])

    if not observe_refs and not passthrough_refs and not drop_refs:
        return records, []

    # Check if any directive references the source namespace
    has_source_refs = (
        any(ref.startswith("source.") for ref in observe_refs)
        or any(ref.startswith("source.") for ref in passthrough_refs)
        or any(ref.startswith("source.") for ref in drop_refs)
    )

    source_index = _build_source_index(source_data) if has_source_refs else {}
    resolved_observe, qualify_wildcards = (
        _resolve_observe_refs_for_flat_keys(observe_refs, action_name)
        if observe_refs
        else ([], False)
    )

    source_cache: dict[tuple[str | None, str | None], dict | None] = {}
    prepared: list[tuple[dict, dict]] = []
    skipped: list[dict] = []

    for record in records:
        content = get_existing_content(record)
        sguid = record.get("source_guid")
        psguid = record.get("parent_source_guid")

        # Build field_context with source namespace resolved
        field_context = dict(content)
        if has_source_refs:
            cache_key = (sguid, psguid)
            if cache_key not in source_cache:
                source_cache[cache_key] = _resolve_source_content(
                    sguid, source_index, source_data, psguid
                )
            source_content = source_cache[cache_key]
            if source_content is None:
                logger.debug(
                    "[%s] Skipping record %s — source_guid matches no record in the "
                    "%d-record source pool",
                    action_name,
                    sguid,
                    len(source_data or []),
                )
                skipped.append({"source_guid": sguid, "reason": SOURCE_UNRESOLVED})
                continue
            if source_content:
                field_context["source"] = source_content

        # Validate observe/passthrough/drop refs against the record's namespaces.
        # RecordContextError means a required namespace or field is missing —
        # skip this record rather than enriching it with None values.
        try:
            apply_context_scope(field_context, context_scope, action_name=action_name)
        except RecordContextError as e:
            logger.debug(
                "[%s] Skipping record %s — observe field missing (upstream incomplete): %s",
                action_name,
                sguid,
                e,
            )
            skipped.append({"source_guid": sguid, "reason": OBSERVE_FIELD_MISSING})
            continue

        # Rebuild enriched record: ALL namespaces preserved, drops applied. Flat
        # keys wait for pass 2 — their names depend on the whole batch.
        enriched_content = deepcopy(content)
        if has_source_refs and source_cache.get((sguid, psguid)):
            enriched_content["source"] = deepcopy(source_cache[(sguid, psguid)])
        _apply_drops_to_content(enriched_content, drop_refs)
        prepared.append((record, enriched_content))

    # Namespace presence can differ per record; reserving the batch union rather
    # than each record's own subset keeps a given ref qualified the same way on
    # every record in this call, not just the ones that happen to carry it.
    namespace_union: frozenset[str] = frozenset(ns for _, content in prepared for ns in content)

    enriched: list[dict] = []
    qualified_keys: set[str] = set()
    for record, enriched_content in prepared:
        qualified_keys |= _inject_flat_observed_keys(
            enriched_content, resolved_observe, qualify_wildcards, action_name, namespace_union
        )
        enriched.append({**record, "content": enriched_content})

    if qualified_keys:
        logger.warning(
            "Action '%s': observed field(s) would have overwritten a namespace or "
            "another observed field on the record. Flat keys are namespace-qualified "
            "(%s) — an action reading the bare key will not find it; read the "
            "qualified key instead.",
            action_name,
            ", ".join(sorted(qualified_keys)),
        )

    if skipped:
        reason_counts = Counter(s["reason"] for s in skipped)
        logger.warning(
            "[%s] %d of %d records skipped — %s",
            action_name,
            len(skipped),
            len(records),
            ", ".join(f"{reason}: {count}" for reason, count in sorted(reason_counts.items())),
        )

    return enriched, skipped
