#!/usr/bin/env python3
"""Analyze field flow across workflow nodes."""

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Pure infrastructure keys excluded from field analysis.
# Subset of agent_actions.prompt.context.scope._RECORD_METADATA_KEYS —
# only keys that are never meaningful UDF inputs.
_METADATA_KEYS = frozenset(
    {
        "target_id",
        "node_id",
        "lineage",
        "_recovery",
        "_unprocessed",
    }
)

# Top-level keys surfaced after content unwrapping.  These live outside
# "content" on structured records but FILE-mode UDFs need them:
#   source_guid   — pipeline preserves it for lineage chaining
#   metadata      — MetadataEnricher writes response metadata here
#   parent/root_target_id, chunk_info — ancestry for reducers/aggregators
_ANCESTRY_KEYS = frozenset(
    {
        "source_guid",
        "parent_target_id",
        "root_target_id",
        "chunk_info",
        "metadata",
    }
)


def get_field_type(value: Any) -> str:
    """Get a simple type description for a value."""
    if value is None:
        return "null"
    elif isinstance(value, bool):
        return "bool"
    elif isinstance(value, int):
        return "int"
    elif isinstance(value, float):
        return "float"
    elif isinstance(value, str):
        return "str"
    elif isinstance(value, list):
        if not value:
            return "list[]"
        elem_type = get_field_type(value[0])
        return f"list[{elem_type}]"
    elif isinstance(value, dict):
        return "dict"
    return "unknown"


def extract_fields(data: dict) -> dict[str, str]:
    """Extract field names and types from data.

    When a content wrapper is present, unwraps to content but also surfaces
    top-level _ANCESTRY_KEYS (source_guid, parent/root_target_id, chunk_info,
    metadata) since FILE-mode UDFs may need them.
    """
    raw = data
    if "content" in data and isinstance(data["content"], dict):
        data = data["content"]

    fields = {}
    for key, value in data.items():
        if key in _METADATA_KEYS:
            continue
        fields[key] = get_field_type(value)

    # When content was unwrapped, surface ancestry keys from the top level —
    # FILE-mode reducers need these (e.g., grouping by root_target_id).
    if raw is not data:
        for key in _ANCESTRY_KEYS:
            if key in raw and key not in fields:
                fields[key] = get_field_type(raw[key])

    return fields


def load_node_data(node_dir: Path) -> dict[str, str] | None:
    """Load and extract fields from a node's output.

    Returns:
        None  — no JSON files exist in the directory; node is skipped entirely.
        {}    — a JSON file was found but was unreadable/malformed; node is
                included with zero fields so it still appears in the flow diff.
        dict  — successfully extracted field-name → type-string mapping.
    """
    json_files = list(node_dir.glob("combined_*.json"))
    if not json_files:
        json_files = list(node_dir.glob("*.json"))

    if not json_files:
        return None

    try:
        with open(json_files[0]) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON in %s: %s", json_files[0], e)
        return {}
    except OSError as e:
        logger.warning("Could not read %s: %s", json_files[0], e)
        return {}

    if data is None:
        logger.warning("JSON file contained null, expected dict or list")
        return {}

    if isinstance(data, list):
        if not data:
            logger.warning("JSON file contained empty array")
            return {}
        if not isinstance(data[0], dict):
            logger.warning(
                "Expected dict in JSON array, got %s", type(data[0]).__name__
            )
            return {}
        data = data[0]

    if not isinstance(data, dict):
        logger.warning("Expected dict at top level, got %s", type(data).__name__)
        return {}

    return extract_fields(data)


def parse_action_name(dirname: str) -> tuple[int, str]:
    """Parse node directory name into (node_number, action_name)."""
    parts = dirname.split("_", 2)
    if len(parts) >= 3 and parts[0] == "node":
        try:
            return int(parts[1]), "_".join(parts[2:])
        except ValueError:
            pass
    return -1, dirname


def analyze_workflow(target_dir: Path) -> None:
    """Analyze field flow across all nodes."""
    nodes: list[dict[str, Any]] = []

    for node_dir in target_dir.iterdir():
        if not node_dir.is_dir():
            continue

        node_num, action_name = parse_action_name(node_dir.name)
        fields = load_node_data(node_dir)

        if fields is not None:
            nodes.append(
                {"num": node_num, "name": action_name, "dir": node_dir.name, "fields": fields}
            )

    nodes.sort(key=lambda x: x["num"])

    if not nodes:
        print("No node data found in target directory", file=sys.stderr)
        sys.exit(1)

    print("=" * 70)
    print("FIELD FLOW ANALYSIS")
    print("=" * 70)

    prev_fields: set[str] = set()

    for _i, node in enumerate(nodes):
        curr_fields = set(node["fields"].keys())

        added = curr_fields - prev_fields
        removed = prev_fields - curr_fields
        kept = curr_fields & prev_fields

        print(f"\n{'─' * 70}")
        print(f"Node {node['num']}: {node['name']}")
        print(f"{'─' * 70}")
        print(f"Total fields: {len(curr_fields)}")

        if added:
            print(f"\n  + ADDED ({len(added)}):")
            for field in sorted(added):
                print(f"      {field}: {node['fields'][field]}")

        if removed:
            print(f"\n  - REMOVED ({len(removed)}):")
            for field in sorted(removed):
                print(f"      {field}")

        if kept:
            print(f"\n  = KEPT ({len(kept)}): {', '.join(sorted(kept)[:5])}", end="")
            if len(kept) > 5:
                print(f" ... (+{len(kept) - 5} more)")
            else:
                print()

        prev_fields = curr_fields

    print(f"\n{'=' * 70}")
    print("FIELD SUMMARY")
    print("=" * 70)

    all_fields: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        for field, _ftype in node["fields"].items():
            all_fields[field].append(f"node_{node['num']}")

    print(f"\nTotal unique fields: {len(all_fields)}")
    print("\nFields by first appearance:")
    for field in sorted(all_fields.keys()):
        appearances = all_fields[field]
        print(f"  {field}: appears in {len(appearances)} nodes, first at {appearances[0]}")


def main():
    parser = argparse.ArgumentParser(description="Analyze field flow across workflow nodes")
    parser.add_argument("target_dir", help="Path to workflow's agent_io/target directory")

    args = parser.parse_args()

    target_path = Path(args.target_dir)
    if not target_path.exists():
        print(f"Error: Directory not found: {target_path}", file=sys.stderr)
        sys.exit(1)

    analyze_workflow(target_path)


if __name__ == "__main__":
    main()
