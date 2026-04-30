"""Shared utilities for merging JSON records by correlation key."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

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
    """Return the first matching correlation value from top-level or content, or None."""
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
    """Merge a group of records using deep_merge_record (legacy/aggregation path)."""
    merged: dict[str, Any] = {}
    for record in group:
        deep_merge_record(merged, record)
    return merged


def merge_records_by_key(records: list[Any], reduce_key: str | None = None) -> list[Any]:
    """Merge records sharing the same correlation key.

    For same-source fan-in (no ``reduce_key``), uses ``merge_branch_records``
    so each branch contributes only its own namespace and upstream is preserved
    from the base record (first record in the group).  For ``reduce_key``
    aggregation (different sources grouped together), uses ``deep_merge_record``.

    Note: When using the branch-records path, ``group[0]`` is the canonical
    upstream source.  Its shared namespaces survive; other records' versions
    of the same upstream namespaces are ignored.
    """
    if reduce_key is not None and not isinstance(reduce_key, str):
        raise TypeError(
            f"merge_records_by_key: reduce_key must be str or None, got {type(reduce_key).__name__}"
        )

    groups_by_key: dict[str, list[dict[str, Any]]] = {}
    records_without_key: list[Any] = []

    key_candidates: list[str] = []
    if reduce_key:
        key_candidates.append(reduce_key)
    key_candidates.extend(
        ["version_correlation_id", "root_target_id", "parent_target_id", "source_guid"]
    )

    for record in records:
        if not isinstance(record, dict):
            records_without_key.append(record)
            continue

        correlation_value = get_correlation_value(record, key_candidates)
        if correlation_value:
            groups_by_key.setdefault(correlation_value, []).append(record)
        else:
            records_without_key.append(record)

    merged_results: list[Any] = []
    for group in groups_by_key.values():
        if len(group) == 1:
            merged_results.append(group[0])
            continue

        if reduce_key:
            merged_results.append(_merge_group_deep(group))
            continue

        branch_mapping = _identify_branch_mapping(group)
        if branch_mapping is not None:
            merged = merge_branch_records(branch_mapping, base_record=group[0])
            # merge_branch_records handles lineage dedup but not lineage_sources.
            # merged["node_id"] == group[0]["node_id"] (from {**base, ...}).
            for rec in group[1:]:
                _populate_lineage_sources(merged, rec)
            merged_results.append(merged)
        else:
            merged_results.append(_merge_group_deep(group))

    return merged_results + records_without_key


def merge_json_files(file_paths: list[Path], reduce_key: str | None = None) -> list[Any]:
    """Load and merge JSON records from multiple files by correlation key (MapReduce pattern)."""
    all_records: list[Any] = []
    for file_path in file_paths:
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    all_records.extend(data)
                else:
                    all_records.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                "Could not read JSON file for merging: %s - %s",
                file_path,
                e,
            )

    merged = merge_records_by_key(all_records, reduce_key)

    logger.debug(
        "Merged %d records from %d files into %d correlated records (key=%s)",
        len(all_records),
        len(file_paths),
        len(merged),
        reduce_key or "auto",
    )

    return merged
