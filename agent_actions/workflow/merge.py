"""Shared utilities for merging JSON records by correlation key."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agent_actions.logging.diagnostics import DIAGNOSTIC
from agent_actions.processing.record_helpers import upstream_cause
from agent_actions.record.state import CASCADE_BLOCKING_VALUES, RecordState
from agent_actions.utils import deep_json
from agent_actions.utils.content import get_existing_content

logger = logging.getLogger(__name__)


def deep_merge_record(existing: dict[str, Any], new_record: dict[str, Any]) -> None:
    """Merge new_record into existing in place: content dicts merge, lineage deduplicates, other fields first-wins."""
    for key, value in new_record.items():
        if key == "content" and isinstance(value, dict):
            if "content" not in existing:
                existing["content"] = {}
            if isinstance(existing["content"], dict):
                existing["content"].update(value)
            else:
                existing["content"] = value
        elif key == "lineage" and isinstance(value, list):
            _merge_lineage(existing, value)
        elif key == "lineage_sources":
            pass  # Owned by _populate_lineage_sources below
        elif key not in existing:
            existing[key] = value

    _populate_lineage_sources(existing, new_record)


def _merge_lineage(existing: dict[str, Any], new_lineage: list[Any]) -> None:
    """Merge lineage arrays with deduplication by node_id."""
    if "lineage" not in existing:
        existing["lineage"] = []
    if not isinstance(existing["lineage"], list):
        return

    existing_ids: set = set()
    for entry in existing["lineage"]:
        if isinstance(entry, str):
            existing_ids.add(entry)
        elif isinstance(entry, dict) and "node_id" in entry:
            existing_ids.add(entry["node_id"])

    for entry in new_lineage:
        if isinstance(entry, str):
            if entry not in existing_ids:
                existing["lineage"].append(entry)
                existing_ids.add(entry)
        elif isinstance(entry, dict):
            node_id = entry.get("node_id")
            if node_id:
                if node_id not in existing_ids:
                    existing["lineage"].append(entry)
                    existing_ids.add(node_id)
            else:
                existing["lineage"].append(entry)


def _populate_lineage_sources(existing: dict[str, Any], new_record: dict[str, Any]) -> None:
    """Track branch leaf node_ids in lineage_sources when merging parallel branches."""
    existing_node_id = existing.get("node_id")
    new_node_id = new_record.get("node_id")

    if not existing_node_id or not new_node_id:
        return

    if existing_node_id == new_node_id:
        return

    if "lineage_sources" in existing:
        if new_node_id not in existing["lineage_sources"]:
            existing["lineage_sources"].append(new_node_id)
    else:
        existing["lineage_sources"] = [existing_node_id, new_node_id]


def merge_branch_records(
    branch_records: dict[str, dict[str, Any]],
    base_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge N branch records into one, each contributing only its own namespace.

    Args:
        branch_records: {branch_name: record} — each record has accumulated bus
        base_record: Optional base for upstream content. If None, uses first branch.

    Returns:
        Merged record with upstream namespaces once + each branch's own namespace.
        Lineage is deduplicated across all branches.
    """
    if not branch_records:
        return base_record or {}

    base = base_record or next(iter(branch_records.values()))
    merged_content = dict(get_existing_content(base))

    for branch_name, branch_record in branch_records.items():
        branch_content = get_existing_content(branch_record)
        if branch_name not in branch_content:
            logger.warning(
                "Branch '%s' missing own namespace in content. Keys: %s",
                branch_name,
                sorted(branch_content.keys()),
                extra=DIAGNOSTIC,
            )
        else:
            merged_content[branch_name] = branch_content[branch_name]

    result = {**base, "content": merged_content}
    # Copy lineage list so _merge_lineage doesn't mutate the input base_record
    if "lineage" in result and isinstance(result["lineage"], list):
        result["lineage"] = list(result["lineage"])
    for branch_record in branch_records.values():
        _merge_lineage(result, branch_record.get("lineage", []))

    return result


def get_correlation_value(record: dict[str, Any], key_candidates: list[str]) -> str | None:
    """Return the first truthy correlation value from top-level or content, or None.

    Truthy, not merely present: these ids are framework-assigned, so an empty one means
    unassigned rather than a group named "". Presence-gating it merges every unassigned
    record into one and loses the rest.
    """
    for key_name in key_candidates:
        correlation_value = record.get(key_name)
        if not correlation_value:
            content = record.get("content")
            if isinstance(content, dict):
                correlation_value = content.get(key_name)
        if correlation_value:
            return str(correlation_value)
    return None


def _identify_branch_mapping(
    group: list[dict[str, Any]],
) -> dict[str, dict[str, Any]] | None:
    """Identify branch names for a group of fan-in records.

    Returns ``{branch_name: record}`` where each branch_name is a content
    namespace unique to that record.  Returns ``None`` when branches cannot
    be distinguished (e.g. identical content schemas) — caller falls back to
    ``deep_merge_record``.

    When a record owns multiple unique namespaces (diamond dependency), each
    namespace becomes its own entry pointing to the same record.
    """
    if not group:
        return None

    key_sets: list[set[str]] = []
    for rec in group:
        content = get_existing_content(rec)
        if not content:
            return None
        key_sets.append(set(content.keys()))

    shared_keys = key_sets[0].copy()
    for ks in key_sets[1:]:
        shared_keys &= ks

    branch_records: dict[str, dict[str, Any]] = {}
    for rec, ks in zip(group, key_sets, strict=True):
        unique = ks - shared_keys
        if not unique:
            return None  # can't distinguish this record's branch
        for ns_key in sorted(unique):
            branch_records[ns_key] = rec

    return branch_records


def _merge_group_deep(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge a group whose branches cannot be told apart, namespace by namespace."""
    merged: dict[str, Any] = {}
    for record in group:
        deep_merge_record(merged, record)
    return merged


_AUTO_KEY_CANDIDATES = [
    "version_correlation_id",
    "source_guid",
    "root_target_id",
    "parent_target_id",
]


def _has_correlation_key(record: dict[str, Any], key_name: str) -> bool:
    if record.get(key_name):
        return True
    content = record.get("content")
    return isinstance(content, dict) and bool(content.get(key_name))


def _select_universal_key(records: list[dict[str, Any]]) -> str | None:
    """First auto candidate present on every record that carries any candidate.

    Grouping must key every record in the pool on the SAME field: branches of
    one logical record can carry different key sets (a version-merge descendant
    has ``version_correlation_id``, a plain branch does not), and per-record
    key selection would place them in disjoint groups — a silent partial merge.
    Returns None when no candidate is universal (caller falls back to
    per-record selection).
    """
    keyed = [r for r in records if any(_has_correlation_key(r, k) for k in _AUTO_KEY_CANDIDATES)]
    if not keyed:
        return None
    for key_name in _AUTO_KEY_CANDIDATES:
        if all(_has_correlation_key(r, key_name) for r in keyed):
            return key_name
    return None


def merge_records_by_key(records: list[Any]) -> list[Any]:
    """Merge records sharing the same correlation key.

    The grouping key is chosen once for the whole pool (first universal
    candidate, identity keys before lineage keys) so branches carrying
    different key sets still group by their shared identity.  Same-source
    fan-in merges via ``merge_branch_records`` with ``group[0]`` as the
    canonical upstream (its shared namespaces survive); a group whose
    branches cannot be told apart deep-merges instead.
    """
    groups_by_key: dict[str, list[dict[str, Any]]] = {}
    records_without_key: list[Any] = []

    universal_key = _select_universal_key([r for r in records if isinstance(r, dict)])
    auto_candidates = [universal_key] if universal_key is not None else _AUTO_KEY_CANDIDATES

    for record in records:
        if not isinstance(record, dict):
            records_without_key.append(record)
            continue

        correlation_value = get_correlation_value(record, auto_candidates)

        if correlation_value is not None:
            groups_by_key.setdefault(correlation_value, []).append(record)
        else:
            records_without_key.append(record)

    return [_merge_group(group) for group in groups_by_key.values()] + records_without_key


def _merge_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    """One record from the branch records of one logical record, ``group[0]`` the base."""
    if len(group) == 1:
        # Single-branch passthrough — not a fan-in, so no cascade
        # propagation needed.  The record keeps its original _state.
        return group[0]

    branch_mapping = _identify_branch_mapping(group)
    if branch_mapping is not None:
        merged = merge_branch_records(branch_mapping, base_record=group[0])
        # merge_branch_records handles lineage dedup but not lineage_sources.
        # merged["node_id"] == group[0]["node_id"] (from {**base, ...}).
        for rec in group[1:]:
            _populate_lineage_sources(merged, rec)
    else:
        merged = _merge_group_deep(group)
    _propagate_cascade_blocking(merged, group)
    return merged


def split_from(record: dict[str, Any]) -> list[str]:
    """Source ids of the record *record* was split from: its producer, then its source."""
    producers = record.get("producer_source_guids")
    anchors = list(producers) if isinstance(producers, list) and len(producers) == 1 else []
    parent = record.get("parent_source_guid")
    if parent:
        anchors.append(parent)
    return [a for a in anchors if a and a != record.get("source_guid")]


def _two_branches_split(source: str, split_branches: list[str]) -> Exception:
    from agent_actions.errors import WorkflowError

    return WorkflowError(
        f"Branches {split_branches} of a fan-in each returned several records for one "
        f"source record ({source}), and a fan-in pairs a branch's records one to one "
        "with the others' record for the same source. Bring all but one of these "
        "branches to one record per source first, e.g. with a granularity: File tool "
        "that aggregates them.",
        context={"source": source, "branches": split_branches},
    )


def merge_fan_in(sources: list[tuple[str, Any]]) -> list[Any]:
    """Merge the records of a fan-in's branches, one record per logical record.

    *sources* holds ``(branch, records)`` per dependency. Records are grouped as
    ``merge_records_by_key`` groups them. A branch that returned several records for
    one input gives each a new source id, so each lands in a group of its own; such a
    group is paired with the group of the record it was split from, once per split
    record. Two branches split from the same record cannot be paired one to one, and
    raise rather than run on records that hold one branch alone.
    """
    tagged: list[tuple[str, Any]] = []
    for branch, data in sources:
        for record in data if isinstance(data, list) else [data]:
            tagged.append((branch, record))

    universal_key = _select_universal_key([r for _, r in tagged if isinstance(r, dict)])
    auto_candidates = [universal_key] if universal_key is not None else _AUTO_KEY_CANDIDATES

    groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    without_key: list[Any] = []
    group_of_guid: dict[str, str] = {}
    for branch, record in tagged:
        key = get_correlation_value(record, auto_candidates) if isinstance(record, dict) else None
        if key is None:
            without_key.append(record)
            continue
        groups.setdefault(key, []).append((branch, record))
        if record.get("source_guid"):
            group_of_guid.setdefault(str(record["source_guid"]), key)

    def branches(key: str) -> set[str]:
        return {branch for branch, _ in groups[key]}

    splits: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for key in list(groups):
        if len(branches(key)) != 1:
            continue
        (branch,) = branches(key)
        for anchor in split_from(groups[key][0][1]):
            anchor_key = group_of_guid.get(anchor)
            if anchor_key in groups and anchor_key != key and branches(anchor_key) - {branch}:
                splits.setdefault(anchor_key, {}).setdefault(branch, []).extend(
                    record for _, record in groups.pop(key)
                )
                break

    # Split records left alone: from several branches and one source, they have no
    # record of that source to pair with, only each other. Each branch holds two or
    # more of them when it split the source itself; one each is a branch below an
    # earlier split that lacks some of its records, left as it was.
    unpaired: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for key, members in groups.items():
        if len(branches(key)) == 1 and key not in splits:
            for anchor in split_from(members[0][1])[-1:]:
                unpaired.setdefault(anchor, {}).setdefault(members[0][0], []).append(members[0][1])
    for anchor, by_branch in unpaired.items():
        if len(by_branch) > 1 and all(len(found) > 1 for found in by_branch.values()):
            raise _two_branches_split(anchor, sorted(by_branch))

    merged: list[Any] = []
    for key, members in groups.items():
        split = splits.get(key)
        if not split:
            merged.append(_merge_group([record for _, record in members]))
            continue
        split_branches = sorted(split)
        if len(split_branches) > 1 or split_branches[0] in branches(key):
            raise _two_branches_split(key, split_branches)
        others = [record for _, record in members]
        for split_record in split[split_branches[0]]:
            merged.append(_merge_group([split_record, *others]))
    return merged + without_key


def _propagate_cascade_blocking(merged: dict[str, Any], group: list[dict[str, Any]]) -> None:
    """If ANY record in the group has cascade-blocking state, propagate it.

    Fan-in merge with mixed quarantine: if record R2 failed in branch A
    but succeeded in branch B, the merged record inherits cascade_skipped.
    Incomplete data from one branch means the merge is incomplete — the
    record should be retried from the branch where it failed.

    This is an all-or-nothing policy: a single failed branch taints the
    entire merge.  The successful branch data is still present in the
    merged content (the merge runs before this function), but downstream
    actions will cascade-skip the record.  A per-merge ``cascade_policy``
    config (e.g. ``any_success``) could relax this in a future iteration.
    """
    for rec in group:
        state = rec.get("_state")
        if state in CASCADE_BLOCKING_VALUES:
            # The merged record's history is the base branch's, which may not be the
            # branch that blocked it; the tombstone below reads the cause from here.
            cause = upstream_cause(rec)
            merged["_state"] = RecordState.CASCADE_SKIPPED.value
            if cause.get("upstream_action"):
                metadata = merged.get("metadata")
                merged["metadata"] = {**(metadata if isinstance(metadata, dict) else {}), **cause}
            logger.debug(
                "Merge fan-in: propagating cascade-blocking state '%s' "
                "from branch to merged record (source_guid=%s)",
                state,
                merged.get("source_guid", "?"),
            )
            return


def merge_json_files(
    file_paths: list[Path],
    unreadable: list[Path] | None = None,
) -> list[Any]:
    """Load and merge JSON records from multiple files by correlation key.

    Reading fails open: one corrupt file must not abort the merge. That leaves
    the caller a short result and no exception, so ``unreadable`` collects the
    paths that were dropped — the only way to learn that records went missing.
    """
    sources: list[tuple[str, Any]] = []
    for file_path in file_paths:
        try:
            with open(file_path, encoding="utf-8") as f:
                sources.append((str(file_path), deep_json.loads(f.read())))
        except (json.JSONDecodeError, OSError) as e:
            if unreadable is not None:
                unreadable.append(file_path)
            logger.warning(
                "Could not read JSON file for merging: %s - %s",
                file_path,
                e,
            )

    merged = merge_fan_in(sources)

    logger.debug(
        "Merged %d records from %d files into %d correlated records",
        sum(len(data) if isinstance(data, list) else 1 for _, data in sources),
        len(file_paths),
        len(merged),
    )

    return merged
