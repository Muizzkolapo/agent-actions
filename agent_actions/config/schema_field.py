"""Resolve whether a flat schema field is required."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

_EMPTY: frozenset[str] = frozenset()


def field_is_required(
    field: dict[str, Any],
    required_by_default: bool,
    top_level_required: Collection[str] = _EMPTY,
) -> bool:
    """Whether a flat ``fields:`` entry is required.

    An explicit scalar ``required`` wins (a list there is a nested object's own
    required properties, not this field's requiredness); then membership in the
    schema's top-level ``required:`` array; then ``optional`` opts in/out; otherwise the
    schema's ``required_by_default`` decides (default: optional).
    """
    explicit = field.get("required")
    if "required" in field and not isinstance(explicit, list):
        return bool(explicit)
    field_id = field.get("id") or field.get("name")
    if field_id and field_id in top_level_required:
        return True
    if "optional" in field:
        return not bool(field["optional"])
    return required_by_default


def top_level_required_ids(schema: dict[str, Any]) -> frozenset[str]:
    """The schema-level ``required:`` array as a set (empty when absent or malformed)."""
    required = schema.get("required")
    if isinstance(required, list):
        return frozenset(x for x in required if isinstance(x, str))
    return _EMPTY
