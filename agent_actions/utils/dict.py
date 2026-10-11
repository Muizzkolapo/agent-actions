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


def pop_nested_value(data: Any, field_path: str) -> bool:
    """Remove *field_path* by literal key first, then as a dotted path.

    The return value is the point: a caller that withholds a field needs to know when it
    withheld nothing, and `dict.pop(path, None)` cannot tell the two apart.

    Literal first because the framework really stores such a key: an explicitly
    passed-through nested reference keeps its dotted spelling as one key, and
    merge_passthrough_namespaces copies it verbatim into the next record. This is
    extract_field_value's own order, so observe and drop resolve the same reference the
    same way -- traversing only would leave that key in place.
    """
    if not isinstance(data, dict):
        return False
    if field_path in data:
        del data[field_path]
        return True
    if "." not in field_path:
        return False
    keys = field_path.split(".")
    current = data
    for key in keys[:-1]:
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    if not isinstance(current, dict) or keys[-1] not in current:
        return False
    del current[keys[-1]]
    return True


def set_nested_value(data: dict, field_path: str, value: Any) -> None:
    """Set a nested value in a dictionary using dot notation, creating intermediate dicts."""
    keys = field_path.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value
