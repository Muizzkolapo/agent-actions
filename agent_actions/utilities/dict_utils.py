"""Common dictionary utility functions."""

from typing import Any, Optional


def get_nested_value(data: Any, field_path: str) -> Optional[Any]:
    """
    Get a nested value from a dictionary using dot notation.

    Args:
        data: The data structure to search in
        field_path: Dot-separated path to the field (e.g., 'user.name')

    Returns:
        The field value or None if not found
    """
    keys = field_path.split(".")
    value = data

    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None

    return value
