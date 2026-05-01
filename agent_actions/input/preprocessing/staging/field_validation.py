"""Staging field name validation — catches reserved namespace collisions early."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigValidationError
from agent_actions.utils.constants import SPECIAL_NAMESPACES

logger = logging.getLogger(__name__)


def validate_staging_field_names(raw_content: Any, file_path: str) -> None:
    """Validate that staging record field names do not collide with reserved namespaces.

    The framework reserves certain top-level names (``source``, ``version``,
    ``workflow``, ``seed``, etc.) as prompt-context namespaces.  If a staging
    record contains a field with one of these names the pipeline will silently
    mis-route the value at prompt-build time.  Catching the collision here —
    before any processing — gives the user a clear, actionable error.
    """
    if not raw_content:
        return

    # Grab a representative record to inspect field names.
    if isinstance(raw_content, list) and raw_content:
        sample = raw_content[0]
    elif isinstance(raw_content, dict):
        sample = raw_content
    else:
        return

    if not isinstance(sample, dict):
        return

    collisions = SPECIAL_NAMESPACES & sample.keys()
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
