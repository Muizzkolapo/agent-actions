"""Schema format detection utilities for compiled vs inline formats."""

from typing import Any


def is_compiled_schema(schema: dict[str, Any]) -> bool:
    """Check if a schema is in compiled (unified) format.

    Recognizes fields-based format, JSON Schema object format,
    and JSON Schema array format.
    """
    if not isinstance(schema, dict):
        return False  # type: ignore[unreachable]

    if "fields" in schema and isinstance(schema.get("fields"), list):
        return True

    if "type" in schema and "properties" in schema:
        return True

    if schema.get("type") == "array" and "items" in schema:
        return True

    return False


def is_inline_schema_shorthand(schema_value: Any) -> bool:
    """Check if a schema value is in inline shorthand format (e.g. ``{"field": "string!"}``)."""
    if not isinstance(schema_value, dict):
        return False

    if is_compiled_schema(schema_value):
        return False

    if not schema_value:
        return False

    valid_types = {"string", "number", "integer", "boolean", "array", "object"}
    for value in schema_value.values():
        if not isinstance(value, str):
            return False
        check_type = value.rstrip("!")
        if check_type.startswith("array[") and check_type.endswith("]"):
            check_type = "array"
        if check_type not in valid_types:
            return False

    return True
