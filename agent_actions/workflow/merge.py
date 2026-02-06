"""
Shared utilities for merging JSON records by correlation key.

This module provides common merge logic used across the workflow module:
- runner.py (file processing with parallel branches)
- managers/output.py (output merging)
- managers/loop.py (version iteration correlation)

The merge pattern:
1. Group records by a correlation key (reduce_key -> parent_target_id -> source_guid)
2. Deep-merge records with the same key (content dicts, lineage arrays with dedup)
3. Return merged records plus any that couldn't be correlated
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def deep_merge_record(existing: Dict[str, Any], new_record: Dict[str, Any]) -> None:
    """
    Deep merge a new record into an existing record.

    Handles special cases:
    - 'content' dicts are merged (new values update existing)
    - 'lineage' arrays are merged with deduplication (by node_id)
    - Other fields: first occurrence wins

    Args:
        existing: Target record to merge into (modified in place)
        new_record: Source record to merge from
    """
    for key, value in new_record.items():
        if key == "content" and isinstance(value, dict):
            # Deep merge content dictionaries
            if "content" not in existing:
                existing["content"] = {}
            if isinstance(existing["content"], dict):
                existing["content"].update(value)
            else:
                existing["content"] = value
        elif key == "lineage" and isinstance(value, list):
            _merge_lineage(existing, value)
        elif key not in existing:
            # First occurrence wins for non-mergeable fields
            existing[key] = value


def _merge_lineage(existing: Dict[str, Any], new_lineage: List[Any]) -> None:
    """
    Merge lineage arrays with deduplication.

    Lineage entries can be strings (node_ids) or dicts with 'node_id' key.
    """
    if "lineage" not in existing:
        existing["lineage"] = []
    if not isinstance(existing["lineage"], list):
        return

    # Build set of existing node_ids for dedup
    existing_ids: set = set()
    for entry in existing["lineage"]:
        if isinstance(entry, str):
            existing_ids.add(entry)
        elif isinstance(entry, dict) and "node_id" in entry:
            existing_ids.add(entry["node_id"])

    # Add new entries that aren't duplicates
    for entry in new_lineage:
        if isinstance(entry, str):
            if entry not in existing_ids:
                existing["lineage"].append(entry)
                existing_ids.add(entry)
        elif isinstance(entry, dict):
            node_id = entry.get("node_id")
            if node_id:
                # Has node_id: deduplicate by node_id
                if node_id not in existing_ids:
                    existing["lineage"].append(entry)
                    existing_ids.add(node_id)
            else:
                # No node_id: always append (cannot deduplicate)
                existing["lineage"].append(entry)


def get_correlation_value(record: Dict[str, Any], key_candidates: List[str]) -> Optional[str]:
    """
    Find a correlation value from a record using a fallback chain.

    Tries each key candidate in order, checking both top-level and nested
    in 'content' dict.

    Args:
        record: The record to extract correlation value from
        key_candidates: List of field names to try in order

    Returns:
        The correlation value if found, None otherwise
    """
    for key_name in key_candidates:
        correlation_value = record.get(key_name)
        if not correlation_value:
            # Try nested in content
            content = record.get("content", {})
            if isinstance(content, dict):
                correlation_value = content.get(key_name)
        if correlation_value:
            return str(correlation_value)
    return None


def merge_records_by_key(records: List[Any], reduce_key: Optional[str] = None) -> List[Any]:
    """
    Merge records by correlating on a key field.

    Used when processing data from multiple parallel branches.
    Records with the same correlation key are merged into a single record.

    Args:
        records: List of records to merge
        reduce_key: Field name to use for correlation.
                   Falls back to: parent_target_id -> source_guid if not specified.

    Returns:
        List of merged records, correlated by the reduce key
    """
    records_by_key: Dict[str, Dict] = {}
    records_without_key: List[Any] = []

    # Key resolution order: explicit reduce_key -> parent_target_id -> source_guid
    key_candidates = []
    if reduce_key:
        key_candidates.append(reduce_key)
    key_candidates.extend(["parent_target_id", "source_guid"])

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


def merge_json_files(file_paths: List[Path], reduce_key: Optional[str] = None) -> List[Any]:
    """
    Merge JSON contents from multiple files by correlating on a key field.

    Used when processing files from multiple parallel branches that have
    the same filename. Records with the same correlation key are merged into
    a single record with all fields combined (MapReduce pattern).

    For example, if validator_1 outputs {"parent_target_id": "x", "answer_1": "A"}
    and validator_2 outputs {"parent_target_id": "x", "answer_2": "B"},
    the merged result is {"parent_target_id": "x", "answer_1": "A", "answer_2": "B"}.

    Args:
        file_paths: List of paths to JSON files to merge
        reduce_key: Field name to use for correlation (e.g., "parent_target_id").
                   Falls back to: parent_target_id -> source_guid if not specified.

    Returns:
        List of merged records, correlated by the reduce key
    """
    # Collect all records from all files
    all_records: List[Any] = []
    for file_path in file_paths:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    all_records.extend(data)
                else:
                    all_records.append(data)
        except (json.JSONDecodeError, OSError, IOError) as e:
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
