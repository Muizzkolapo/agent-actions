#!/usr/bin/env python3
"""
Generate TypedDict schema from sample JSON data.

Usage:
    python generate_typeddict.py <sample.json> [--output tool.py] [--class-name MyInput]

Example:
    python generate_typeddict.py node_5_output/combined_scraped_sample.json --output my_tool.py
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def infer_python_type(value: Any) -> str:
    """Infer Python type annotation from a JSON value."""
    if value is None:
        return "Any"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        if not value:
            return "List[Any]"
        # Check if all elements are same type
        elem_types = set(infer_python_type(e) for e in value)
        if len(elem_types) == 1:
            elem_type = elem_types.pop()
            return f"List[{elem_type}]"
        return "List[Any]"
    if isinstance(value, dict):
        # Check if it's a simple dict or needs nested TypedDict
        if not value:
            return "dict"
        value_types = set(infer_python_type(v) for v in value.values())
        if len(value_types) == 1:
            return f"Dict[str, {value_types.pop()}]"
        # Mixed value types - use plain dict
        return "dict"
    return "Any"


def extract_fields_from_json(data: dict) -> dict[str, str]:
    """Extract field names and their Python types from JSON data."""
    # Handle content wrapper
    if "content" in data and isinstance(data["content"], dict):
        data = data["content"]

    fields = {}
    for key, value in data.items():
        # Skip internal/metadata fields
        if key in ("source_guid", "target_id", "node_id", "lineage"):
            continue
        fields[key] = infer_python_type(value)

    return fields


def generate_typeddict(
    fields: dict[str, str], class_name: str, source_node: str = "node_N", dest_node: str = "node_M"
) -> str:
    """Generate TypedDict class definition."""

    # Determine required imports
    imports = {"TypedDict"}
    for type_str in fields.values():
        if "List" in type_str:
            imports.add("List")
        if "Dict" in type_str:
            imports.add("Dict")
        if "Any" in type_str:
            imports.add("Any")

    imports_str = ", ".join(sorted(imports))

    # Group fields by category (heuristic)
    core_fields = []
    metadata_fields = []

    for name, type_str in fields.items():
        if name in ("batch_name", "question_type", "source_guid"):
            metadata_fields.append((name, type_str))
        else:
            core_fields.append((name, type_str))

    # Build class body
    lines = [
        f"from typing import {imports_str}",
        "from agent_actions import udf_tool",
        "",
        "",
        f"class {class_name}(TypedDict, total=False):",
        '    """Input schema for function.',
        "",
        f"    Source: {source_node} output",
        f"    Destination: {dest_node} output",
        '    """',
    ]

    if core_fields:
        lines.append("    # Core fields")
        for name, type_str in core_fields:
            lines.append(f"    {name}: {type_str}")

    if metadata_fields:
        lines.append("")
        lines.append("    # Metadata fields")
        for name, type_str in metadata_fields:
            lines.append(f"    {name}: {type_str}")

    return "\n".join(lines)


def main():
    """CLI entry point for TypedDict generation."""
    parser = argparse.ArgumentParser(description="Generate TypedDict schema from sample JSON")
    parser.add_argument("json_file", help="Path to sample JSON file")
    parser.add_argument(
        "--output", "-o", help="Output Python file (prints to stdout if not specified)"
    )
    parser.add_argument(
        "--class-name",
        "-c",
        default="ToolInput",
        help="Name for the TypedDict class (default: ToolInput)",
    )
    parser.add_argument(
        "--source-node",
        "-s",
        default="node_N_previous_action",
        help="Source node name for docstring",
    )
    parser.add_argument(
        "--dest-node",
        "-d",
        default="node_M_this_action",
        help="Destination node name for docstring",
    )

    args = parser.parse_args()

    # Load JSON
    json_path = Path(args.json_file)
    if not json_path.exists():
        print(f"Error: File not found: {json_path}", file=sys.stderr)
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    # Handle array of records
    if isinstance(data, list) and data:
        data = data[0]

    # Extract fields
    fields = extract_fields_from_json(data)

    if not fields:
        print("Error: No fields found in JSON", file=sys.stderr)
        sys.exit(1)

    # Generate TypedDict
    result = generate_typeddict(fields, args.class_name, args.source_node, args.dest_node)

    # Output
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(result, encoding="utf-8")
        print(f"Generated TypedDict written to: {output_path}")
    else:
        print(result)


if __name__ == "__main__":
    main()
