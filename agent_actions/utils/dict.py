"""Common dictionary utility functions."""

from typing import Any, Optional

_MISSING = object()


def get_nested_value(data: Any, field_path: str, default: Any = None) -> Optional[Any]:
    """
    Get a nested value from a dictionary using dot notation.

    Args:
        data: The data structure to search in
        field_path: Dot-separated path to the field (e.g., 'user.name')
        default: Value to return if path not found (default: None)

    Returns:
        The field value or *default* if not found
    """
    keys = field_path.split(".")
    value = data

    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default

    return value


def nested_field_exists(data: Any, field_path: str) -> bool:
    """Check whether a dot-separated path exists in a nested dict."""
    return get_nested_value(data, field_path, default=_MISSING) is not _MISSING


def set_nested_value(data: dict, field_path: str, value: Any) -> None:
    """
    Set a nested value in a dictionary using dot notation, creating intermediate dicts.

    Args:
        data: The dictionary to set the value in
        field_path: Dot-separated path to the field (e.g., 'user.name')
        value: The value to set
    """
    keys = field_path.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value
