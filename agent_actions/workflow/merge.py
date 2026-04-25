"""Shared utilities for merging JSON records by correlation key."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

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


def merge_records_by_key(records: list[Any], reduce_key: str | None = None) -> list[Any]:
    """Merge records sharing the same correlation key (reduce_key -> parent_target_id -> source_guid)."""
    records_by_key: dict[str, dict] = {}
    records_without_key: list[Any] = []

    key_candidates = []
    if reduce_key:
        key_candidates.append(reduce_key)
    key_candidates.extend(["root_target_id", "parent_target_id", "source_guid"])

    for record in records:
        if not isinstance(record, dict):
            records_without_key.append(record)
            continue

        correlation_value = get_correlation_value(record, key_candidates)

        if correlation_value:
            if correlation_value not in records_by_key:
                records_by_key[correlation_value] = {}
            deep_merge_record(records_by_key[correlation_value], record)
        else:
            records_without_key.append(record)

    return list(records_by_key.values()) + records_without_key


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
