"""Common dictionary utility functions."""

from typing import Any

_MISSING = object()


def get_nested_value(data: Any, field_path: str, default: Any = None) -> Any | None:
    """Get a nested value from a dictionary using dot-separated *field_path*."""
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
    """Set a nested value in a dictionary using dot notation, creating intermediate dicts."""
    keys = field_path.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value
