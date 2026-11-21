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

    if schema.get("type") == "object" and isinstance(schema.get("properties"), dict):
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
            # Non-string values cause AttributeError in downstream .endswith("!")
            # calls. Reject here so callers get False, not a crash.
            return False
        check_type = value.rstrip("!")
        if check_type.startswith("array[") and check_type.endswith("]"):
            check_type = "array"
        if check_type not in valid_types:
            return False

    return True


def bare_array_fields(schema: dict[str, Any]) -> list[str]:
    """Shorthand fields typed ``array`` with no item type, which compile to an array of strings."""
    return [
        name
        for name, value in schema.items()
        if isinstance(value, str) and value.rstrip("!") == "array"
    ]


def bare_array_warning(owner: str, field: str) -> str:
    return (
        f"{owner}: inline schema field '{field}' is a bare 'array', so it is read as an "
        "array of strings and an item of any other type fails. Write 'array[string]' "
        "for strings or 'array[object]' for objects."
    )
