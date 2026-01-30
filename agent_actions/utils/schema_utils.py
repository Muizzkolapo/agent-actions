"""
Shared utilities for schema format detection.

These utilities help identify the format of schema definitions across
the codebase, ensuring consistent detection of compiled vs inline formats.
"""

from typing import Any, Dict


def is_compiled_schema(schema: Dict[str, Any]) -> bool:
    """
    Check if a schema is in compiled (unified) format.

    Compiled schemas are produced by the render step and have one of these formats:

    1. Fields-based format (from inline schema expansion):
       {
           "name": "my_schema",
           "fields": [{"id": "field1", "type": "string"}, ...],
           "description": "...",
           "required": [...],
           "additionalProperties": False
       }

    2. JSON Schema format (from schema/ directory):
       {
           "type": "object",
           "properties": {...}
       }

    3. JSON Schema array format:
       {
           "type": "array",
           "items": {...}
       }

    Args:
        schema: Schema dictionary to check

    Returns:
        True if compiled format, False if inline shorthand format
    """
    if not isinstance(schema, dict):
        return False

    # Check for fields-based unified format (from render compilation)
    if "fields" in schema and isinstance(schema.get("fields"), list):
        return True

    # Check for JSON Schema format (type + properties)
    if "type" in schema and "properties" in schema:
        return True

    # Check for JSON Schema array format
    if schema.get("type") == "array" and "items" in schema:
        return True

    return False


def is_inline_schema_shorthand(schema_value: Any) -> bool:
    """
    Check if a schema value is in inline shorthand format.

    Inline shorthand format: {"field_name": "string", "count": "number!"}
    Where keys are field names and values are type strings.

    Args:
        schema_value: Schema value to check

    Returns:
        True if inline shorthand format, False otherwise
    """
    if not isinstance(schema_value, dict):
        return False

    # Already compiled format
    if is_compiled_schema(schema_value):
        return False

    # Empty dict is not an inline schema
    if not schema_value:
        return False

    # Check if all values are type strings (inline schema format)
    valid_types = {"string", "number", "integer", "boolean", "array", "object"}
    for value in schema_value.values():
        if not isinstance(value, str):
            return False
        # Strip required marker for type check
        check_type = value.rstrip("!")
        # Handle array[type] format
        if check_type.startswith("array[") and check_type.endswith("]"):
            check_type = "array"
        if check_type not in valid_types:
            return False

    return True
