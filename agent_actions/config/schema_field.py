"""Resolve whether a flat schema field is required."""

from __future__ import annotations

from typing import Any


def field_is_required(field: dict[str, Any], required_by_default: bool) -> bool:
    """Whether a flat ``fields:`` entry is required.

    Explicit ``required`` wins; then ``optional`` opts in/out; otherwise the
    schema's ``required_by_default`` decides (default: optional).
    """
    if "required" in field:
        return bool(field["required"])
    if "optional" in field:
        return not bool(field["optional"])
    return required_by_default
