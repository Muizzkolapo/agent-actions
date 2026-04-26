"""File-mode observe filtering — reads from record's namespaced content."""

import logging
from collections import Counter

from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.io_events import ContextFieldSkippedEvent
from agent_actions.prompt.context.scope_namespace import _extract_content_data
from agent_actions.prompt.context.scope_parsing import parse_field_reference
from agent_actions.utils.content import get_existing_content

logger = logging.getLogger(__name__)

__all__ = [
    "apply_observe_for_file_mode",
]


def _resolve_observe_refs(
    observe_refs: list[str],
    action_name: str = "unknown",
) -> list[tuple[str, str, str]]:
    """Parse observe refs and detect bare-key collisions.

    Returns list of ``(namespace, field_name, output_key)`` triples.

    * *namespace* -- the action/source prefix (left of the dot).
    * *field_name* -- the bare field name (right of the dot) or ``*``.
    * *output_key* -- the key to use in the filtered output dict.  Bare by
      default; qualified (``namespace.field``) when collisions are detected.
    """
    parsed: list[tuple[str, str, str]] = []  # will be re-keyed below
    valid_pairs: list[tuple[str, str]] = []  # (namespace, field_name)

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

    # Detect bare-key collisions across all namespaces.
    bare_counts = Counter(field for _, field in valid_pairs)
    collisions = {k for k, v in bare_counts.items() if v > 1}

    for ns, field in valid_pairs:
        output_key = f"{ns}.{field}" if field in collisions else field
        parsed.append((ns, field, output_key))

    return parsed


def apply_observe_for_file_mode(
    data: list[dict],
    agent_config: dict,
    agent_name: str,
    agent_indices: dict[str, int] | None = None,
    file_path: str | None = None,
    source_data: list[dict] | None = None,
) -> list[dict]:
    """Namespace-aware observe filter for file-mode (array-level) data.

    With the additive content model, every previous action's output is
    stored under its namespace on each record.  Observe refs select
    fields from these namespaces — no storage backend lookup required.

    The ``source`` namespace is the only cross-record reference: it is
    resolved from *source_data* (the original input file records).

    Returns a new list of enriched records with observed fields injected
    into each record's content.
    """
    context_scope = agent_config.get("context_scope") or {}
    observe_refs = context_scope.get("observe")
    if not observe_refs:
        return data

    resolved = _resolve_observe_refs(observe_refs, action_name=agent_name)
    if not resolved:
        return data

    # Single pass over resolved refs: collect wildcards and detect source refs.
    wildcard_ns: set[str] = set()
    has_source_refs = False
    for ns, field, _ in resolved:
        if field == "*":
            wildcard_ns.add(ns)
        if ns == "source":
            has_source_refs = True
    # Qualify wildcard-expanded keys with namespace when multiple
    # wildcards exist (prevents bare-key collisions across namespaces).
    qualify_wildcards = len(wildcard_ns) > 1

    # Build source index for "source" namespace (the only cross-record ref).
    source_index: dict[str | None, dict] = {}
    fallback_source = source_data[0] if source_data else None
    if has_source_refs and source_data:
        for src in source_data:
            sguid = src.get("source_guid") if isinstance(src, dict) else None
            if sguid:
                source_index[sguid] = src

    # Per-record loop: extract observed fields from namespaced content.
    source_content_cache: dict[str | None, dict] = {}
    filtered: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            filtered.append(item)  # type: ignore[unreachable]
            continue

        content = get_existing_content(item)

        # Shallow-copy to avoid mutating caller's data.
        enriched = dict(item)
        enriched_content = dict(content)

        # Resolve source content once per item, cached by source_guid.
        source_ns_data: dict = {}
        if has_source_refs:
            sguid = item.get("source_guid")
            if sguid not in source_content_cache:
                matched = source_index.get(sguid, fallback_source)
                source_content_cache[sguid] = _extract_content_data(matched) if matched else {}
            source_ns_data = source_content_cache[sguid]

        for ns, field, output_key in resolved:
            if ns == "source":
                ns_data = source_ns_data
            else:
                ns_data = content.get(ns, {})
                if not isinstance(ns_data, dict):
                    ns_data = {}

            if field == "*":
                for f, v in ns_data.items():
                    key = f"{ns}.{f}" if qualify_wildcards else f
                    enriched_content[key] = v
            elif field in ns_data:
                enriched_content[output_key] = ns_data[field]
            else:
                logger.debug(
                    "[FILE OBSERVE] Field '%s' (ns='%s') not found for action '%s'. "
                    "ns_data keys=%s.",
                    field,
                    ns,
                    agent_name,
                    list(ns_data.keys()),
                )

        enriched["content"] = enriched_content
        filtered.append(enriched)

    return filtered
