"""File-mode observe filtering for namespace-aware context resolution."""

import logging
from collections import Counter
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.io_events import ContextFieldSkippedEvent
from agent_actions.prompt.context.scope_inference import infer_dependencies
from agent_actions.prompt.context.scope_namespace import (
    _extract_content_data,
    _load_historical_node,
)
from agent_actions.prompt.context.scope_parsing import parse_field_reference

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


def _load_file_mode_cross_namespace_data(
    needed_ns: set,
    record: dict,
    agent_name: str,
    agent_indices: dict[str, int] | None = None,
    file_path: str | None = None,
    source_record: dict | None = None,
    storage_backend: Optional["StorageBackend"] = None,
) -> dict[str, dict]:
    """Load data for namespaces NOT present in the per-record content.

    Returns ``{namespace: {field: value}}`` for source and context-dep
    namespaces.  Input-source namespaces (whose data lives in each record's
    ``content``) are *not* loaded here.

    *needed_ns* is the set of namespace identifiers that require
    cross-namespace loading, pre-computed by the caller (which applies
    the ``has_reliable_ns`` gate).  This method must not recompute it.

    Called once per unique ancestry key in a file; the caller caches the
    result so that records sharing the same key skip redundant I/O.
    """
    cross_ns: dict[str, dict] = {}

    # Defensive copy -- we mutate via discard below.
    needed_ns = set(needed_ns)

    if not needed_ns:
        return cross_ns

    # --- "source" namespace: use the matched source record ----
    if "source" in needed_ns:
        needed_ns.discard("source")
        if source_record:
            cross_ns["source"] = _extract_content_data(source_record)
        else:
            logger.warning(
                "[FILE OBSERVE] 'source' namespace referenced but no source_record available "
                "for action '%s'.",
                agent_name,
            )

    # --- context dependency namespaces: load via historical lookup -----
    if needed_ns and record and agent_indices and file_path:
        lineage = record.get("lineage", [])
        source_guid = record.get("source_guid")
        current_idx = agent_indices.get(agent_name, 999)

        for ns in needed_ns:
            dep_idx = agent_indices.get(ns)
            if dep_idx is None:
                logger.warning(
                    "[FILE OBSERVE] Namespace '%s' not found in agent_indices for action '%s'. "
                    "Available: %s. Skipping.",
                    ns,
                    agent_name,
                    list(agent_indices.keys()),
                )
                continue
            if dep_idx >= current_idx:
                logger.debug(
                    "[FILE OBSERVE] Skipping namespace '%s' (comes after current action '%s').",
                    ns,
                    agent_name,
                )
                continue

            if not source_guid:
                logger.warning(
                    "[FILE OBSERVE] Cannot load namespace '%s': record has no "
                    "source_guid. action='%s'.",
                    ns,
                    agent_name,
                )
                continue

            try:
                hist = _load_historical_node(
                    action_name=ns,
                    lineage=lineage,
                    source_guid=source_guid,
                    file_path=file_path,
                    agent_indices=agent_indices,
                    parent_target_id=record.get("parent_target_id"),
                    root_target_id=record.get("root_target_id"),
                    storage_backend=storage_backend,
                )
                if hist:
                    cross_ns[ns] = hist
                else:
                    logger.warning(
                        "[FILE OBSERVE] Historical data not found for namespace '%s'. "
                        "action='%s', source_guid=%s.",
                        ns,
                        agent_name,
                        source_guid,
                    )
            except (OSError, KeyError, TypeError, ValueError, AttributeError):
                logger.warning(
                    "[FILE OBSERVE] Failed to load historical data for namespace '%s'. "
                    "action='%s'. Skipping.",
                    ns,
                    agent_name,
                    exc_info=True,
                )
    elif needed_ns:
        for ns in needed_ns:
            logger.warning(
                "[FILE OBSERVE] Cannot load namespace '%s': missing agent_indices/file_path/record "
                "for action '%s'. Skipping.",
                ns,
                agent_name,
            )

    return cross_ns


def apply_observe_for_file_mode(
    data: list[dict],
    agent_config: dict,
    agent_name: str,
    agent_indices: dict[str, int] | None = None,
    file_path: str | None = None,
    source_data: list[dict] | None = None,
    storage_backend: Optional["StorageBackend"] = None,
) -> list[dict]:
    """Namespace-aware observe filter for file-mode (array-level) data.

    Replaces the simplified ``_apply_observe_filter`` which stripped
    namespaces and looked up bare keys in the record content.  This method
    resolves cross-namespace references (``source.url``, context deps)
    correctly.

    Returns a filtered ``List[Dict]`` with the same shape as the old method
    so downstream callers (``_process_file_mode_tool``,
    ``_process_file_mode_hitl``) are unaffected.
    """
    context_scope = agent_config.get("context_scope") or {}
    observe_refs = context_scope.get("observe")
    if not observe_refs:
        return data

    resolved = _resolve_observe_refs(observe_refs, action_name=agent_name)
    if not resolved:
        return data

    # Track which namespaces use wildcards (expanded per-record below).
    wildcard_ns: set[str] = {ns for ns, field, _ in resolved if field == "*"}
    # Qualify wildcard-expanded keys with namespace when multiple
    # wildcards exist (prevents bare-key collisions across namespaces).
    qualify_wildcards = len(wildcard_ns) > 1

    # Determine which namespaces are "input sources" (data in each record).
    # Use fan-in-aware inference so non-primary deps are loaded historically.
    # `has_reliable_ns` tracks whether input_source_names contains real
    # namespace identifiers (from deps/infer_dependencies) vs content-key
    # guesses.  When True, we can safely gate content fallback to only
    # input-source namespaces; when False we must allow it for all refs.
    input_source_names: set = set()
    has_reliable_ns = False
    if agent_indices:
        try:
            input_sources, _ = infer_dependencies(
                agent_config, list(agent_indices.keys()), agent_name
            )
            input_source_names = set(input_sources)
            has_reliable_ns = bool(input_source_names)
        except Exception:
            logger.warning(
                "[FILE OBSERVE] infer_dependencies failed for '%s'; "
                "falling back to raw dependencies.",
                agent_name,
                exc_info=True,
            )

    if not input_source_names:
        # Fallback: raw dependencies or content-key heuristic.
        deps = (
            agent_config["dependencies"]
            if "dependencies" in agent_config
            else agent_config.get("depends_on")
        )
        if deps:
            if isinstance(deps, str):
                input_source_names = {deps}
            else:
                input_source_names = {d for d in deps if isinstance(d, str)}
            has_reliable_ns = True
        elif data and isinstance(data[0], dict):
            # Best-effort heuristic: treat all top-level keys in record
            # content as input-source namespaces.  This can misclassify a
            # key that coincidentally matches a namespace name, but without
            # explicit dependencies there is no reliable way to distinguish
            # input-source keys from metadata.  has_reliable_ns stays False.
            sample = data[0]
            sample_content = (
                sample.get("content", sample) if isinstance(sample.get("content"), dict) else sample
            )
            input_source_names = set(sample_content.keys())

    # Determine which namespaces need cross-namespace loading.
    # "source" is always a known cross-namespace ref (loaded from
    # source_data, not historical lookups) so it is always eligible.
    # Other namespaces require has_reliable_ns because when
    # input_source_names contains content keys (heuristic), the
    # `ns not in input_source_names` check would misclassify every
    # namespace as cross-namespace and trigger spurious historical
    # loads whose stale results would shadow live record data.
    needed_ns: set = set()
    for ns, _field, _ in resolved:
        if ns == "source":
            needed_ns.add(ns)
        elif has_reliable_ns and ns not in input_source_names:
            needed_ns.add(ns)

    # Build source index for matching source records by source_guid.
    source_index: dict[str | None, dict] = {}
    if "source" in needed_ns and source_data:
        for src in source_data:
            sguid = src.get("source_guid") if isinstance(src, dict) else None
            if sguid:
                source_index[sguid] = src

    # Per-record loop with ancestry-aware cache.
    # Historical lookups depend on source_guid + lineage + parent/root target IDs,
    # so the cache key must include all discriminators to avoid returning stale
    # data when records share a source_guid but diverge in ancestry.
    cross_ns_cache: dict[tuple, dict[str, dict]] = {}
    filtered: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            filtered.append(item)  # type: ignore[unreachable]
            continue

        content = item.get("content", item) if isinstance(item.get("content"), dict) else item

        # Resolve cross-namespace data (cached by ancestry key).
        if needed_ns:
            sguid = item.get("source_guid")
            cache_key = (
                sguid,
                tuple(item.get("lineage", [])),
                item.get("parent_target_id"),
                item.get("root_target_id"),
            )
            if cache_key not in cross_ns_cache:
                matched_source = source_index.get(sguid, source_data[0] if source_data else None)
                cross_ns_cache[cache_key] = _load_file_mode_cross_namespace_data(
                    needed_ns=needed_ns,
                    record=item,
                    agent_name=agent_name,
                    agent_indices=agent_indices,
                    file_path=file_path,
                    source_record=matched_source,
                    storage_backend=storage_backend,
                )
            cross_ns_data = cross_ns_cache[cache_key]
        else:
            cross_ns_data = {}

        ordered: dict[str, Any] = {}
        for ns, field, output_key in resolved:
            if field == "*":
                ns_data = None
                if ns in cross_ns_data:
                    ns_data = cross_ns_data[ns]
                elif not has_reliable_ns or ns in input_source_names:
                    ns_data = content
                if ns_data:
                    for f, v in ns_data.items():
                        key = f"{ns}.{f}" if qualify_wildcards else f
                        ordered[key] = v
                continue

            # Cross-namespace data takes priority for non-input namespaces.
            if ns in cross_ns_data and field in cross_ns_data[ns]:
                ordered[output_key] = cross_ns_data[ns][field]
            # Input source (per-record content) -- only when ns is actually
            # an input source.  Without this guard, an unresolved non-input
            # namespace (e.g. dep_b) would silently grab a same-named field
            # from the primary record, producing incorrect context.
            # When has_reliable_ns is False (content-key heuristic), we
            # allow the fallback for all refs since we can't distinguish
            # input namespaces from others.
            elif (not has_reliable_ns or ns in input_source_names) and field in content:
                ordered[output_key] = content[field]
            # Field not found anywhere -- skip silently (logged at debug).
            else:
                logger.debug(
                    "[FILE OBSERVE] Field '%s' (ns='%s') not found for action '%s'. "
                    "content keys=%s, cross_ns keys=%s.",
                    field,
                    ns,
                    agent_name,
                    list(content.keys()),
                    list(cross_ns_data.get(ns, {}).keys()),
                )

        filtered.append(ordered)

    return filtered
