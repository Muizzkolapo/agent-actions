"""Path safety utilities for output containment and filesystem name sanitization."""

from __future__ import annotations

import hashlib
from pathlib import Path


def assert_path_contained(child: Path, parent: Path) -> Path:
    """Resolve both paths and raise ValueError if child escapes parent.

    Resolves symlinks before comparison to prevent symlink traversal.

    Args:
        child: The path to validate.
        parent: The containment boundary.

    Returns:
        The resolved child path.

    Raises:
        ValueError: If the resolved child is not under the resolved parent.
    """
    resolved_child = child.resolve()
    resolved_parent = parent.resolve()
    if not resolved_child.is_relative_to(resolved_parent):
        raise ValueError(
            f"Path escapes containment: {resolved_child} is not under {resolved_parent}"
        )
    return resolved_child


def sanitize_path_component(name: str, max_bytes: int = 200) -> str:
    """Sanitize a string for use as a filesystem path component.

    Replaces path separators and null bytes. If the encoded name exceeds
    *max_bytes*, truncates and appends a short hash to avoid collisions.

    Args:
        name: Raw name (e.g., action name).
        max_bytes: Maximum byte length before truncation (default 200).

    Returns:
        A filesystem-safe, deterministic string.
    """
    safe = name.replace("/", "_").replace("\\", "_").replace("\0", "_")
    encoded = safe.encode("utf-8")
    if len(encoded) <= max_bytes:
        return safe
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    suffix = hashlib.sha256(name.encode()).hexdigest()[:8]
    return f"{truncated}_{suffix}"
