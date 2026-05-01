"""Staging field name validation — catches reserved namespace collisions early."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigValidationError
from agent_actions.utils.constants import SPECIAL_NAMESPACES


def validate_staging_field_names(raw_content: Any, file_path: str) -> None:
    """Validate that staging record field names do not collide with reserved namespaces.

    The framework reserves top-level names in ``SPECIAL_NAMESPACES``
    (``source``, ``version``, ``workflow``, ``seed``, ``prompt``,
    ``schema``, ``action``) as prompt-context namespaces.  If a staging
    record contains a field with one of these names the pipeline will
    silently mis-route the value at prompt-build time.

    For list inputs every dict row is checked, not just the first — staging
    files can contain heterogeneous records.
    """
    if not raw_content:
        return

    if isinstance(raw_content, dict):
        _check_dict(raw_content, file_path)
    elif isinstance(raw_content, list):
        for item in raw_content:
            if isinstance(item, dict):
                _check_dict(item, file_path)


def _check_dict(record: dict[str, Any], file_path: str) -> None:
    """Raise ``ConfigValidationError`` if *record* has reserved field names."""
    collisions = SPECIAL_NAMESPACES & record.keys()
    if collisions:
        collision_list = ", ".join(sorted(collisions))
        reserved_list = ", ".join(sorted(SPECIAL_NAMESPACES))
        raise ConfigValidationError(
            f"Staging data field(s) {collision_list!r} in {Path(file_path).name} "
            f"collide with reserved namespace names.\n\n"
            f"Reserved names: {reserved_list}\n\n"
            f"Rename the colliding field(s) in your staging data "
            f"(e.g. 'source' → 'source_file', 'version' → 'doc_version').",
        )
