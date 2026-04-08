"""Change tracking between catalog generations.

Compares file modification times of project resources between the current
scan and the previous catalog.json to produce added/modified/removed changesets.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

_CATEGORIES = ("workflows", "prompts", "schemas", "tools")


class ResourceChangeset(TypedDict):
    added: list[str]
    modified: list[str]
    removed: list[str]


class ChangesSummary(TypedDict):
    total_added: int
    total_modified: int
    total_removed: int


class CatalogChanges(TypedDict):
    previous_generated_at: str | None
    is_first_run: bool
    summary: ChangesSummary
    workflows: ResourceChangeset
    prompts: ResourceChangeset
    schemas: ResourceChangeset
    tools: ResourceChangeset


def _get_mtime(file_path: str | None) -> float | None:
    """Get file modification time, returning None if the file doesn't exist."""
    if not file_path:
        return None
    try:
        return os.path.getmtime(file_path)
    except OSError:
        return None


def _collect_mtimes(
    data: dict[str, Any] | None, key: str, project_root: Path | None = None
) -> dict[str, float]:
    """Extract mtimes from a scanner result dict using the given source-file key."""
    result: dict[str, float] = {}
    for name, entry in (data or {}).items():
        raw_path = entry.get(key)
        if raw_path and project_root and not os.path.isabs(raw_path):
            raw_path = str(project_root / raw_path)
        mtime = _get_mtime(raw_path)
        if mtime is not None:
            result[name] = mtime
    return result


def collect_resource_mtimes(
    workflows_data: dict[str, dict[str, Any]],
    prompts_data: dict[str, Any],
    schemas_data: dict[str, Any],
    tool_functions_data: dict[str, Any],
    project_root: Path | None = None,
) -> dict[str, dict[str, float]]:
    """Collect file modification times for all tracked resource categories.

    Returns ``{category: {resource_name: mtime_float}}``.
    """
    # Workflows need special handling: two-key fallback (rendered or original)
    wf_mtimes: dict[str, float] = {}
    for wf_name, paths in (workflows_data or {}).items():
        file_path = paths.get("rendered") or paths.get("original")
        mtime = _get_mtime(str(file_path) if file_path else None)
        if mtime is not None:
            wf_mtimes[wf_name] = mtime

    return {
        "workflows": wf_mtimes,
        "prompts": _collect_mtimes(prompts_data, "source_file"),
        "schemas": _collect_mtimes(schemas_data, "source_file"),
        "tools": _collect_mtimes(tool_functions_data, "file_path", project_root),
    }


def load_previous_mtimes(
    catalog_path: Path,
) -> tuple[dict[str, dict[str, float]], str | None]:
    """Load ``resource_mtimes`` and ``generated_at`` from a previous catalog.json.

    Returns ``(mtimes_dict, previous_generated_at)``.
    If the file doesn't exist or lacks a mtimes section, returns empty dict and None.
    """
    if not catalog_path.exists():
        return {}, None

    try:
        with open(catalog_path, encoding="utf-8") as f:
            prev_catalog = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Could not load previous catalog for change tracking: %s", exc)
        return {}, None

    prev_mtimes = prev_catalog.get("resource_mtimes", {})
    prev_generated_at = prev_catalog.get("metadata", {}).get("generated_at")
    return prev_mtimes, prev_generated_at


def compute_changes(
    current_mtimes: dict[str, dict[str, float]],
    previous_mtimes: dict[str, dict[str, float]],
    previous_generated_at: str | None,
) -> CatalogChanges:
    """Compute the changeset between two mtime snapshots.

    Returns a typed dict with per-category added/modified/removed lists
    and a summary with totals.
    """
    summary: ChangesSummary = {"total_added": 0, "total_modified": 0, "total_removed": 0}
    category_changes: dict[str, ResourceChangeset] = {}

    for category in _CATEGORIES:
        curr = current_mtimes.get(category, {})
        prev = previous_mtimes.get(category, {})

        added = sorted(k for k in curr if k not in prev)
        removed = sorted(k for k in prev if k not in curr)
        modified = sorted(k for k in curr if k in prev and curr[k] != prev[k])

        category_changes[category] = {
            "added": added,
            "modified": modified,
            "removed": removed,
        }

        summary["total_added"] += len(added)
        summary["total_modified"] += len(modified)
        summary["total_removed"] += len(removed)

    return {
        "previous_generated_at": previous_generated_at,
        "is_first_run": not previous_mtimes,
        "summary": summary,
        **category_changes,  # type: ignore[typeddict-item]
    }
