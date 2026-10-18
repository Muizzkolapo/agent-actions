"""Staging record checks that run before any record is prepared or sent."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigValidationError
from agent_actions.prompt.context.seed_entry import SeedSelectionError, selected_seed_entries
from agent_actions.utils.constants import SPECIAL_NAMESPACES

logger = logging.getLogger(__name__)


def validate_seed_selectors(
    raw_content: Any, file_path: str, action_configs: Mapping[str, Mapping[str, Any]]
) -> None:
    """Refuse a staged file with a row that no file of a selected seed covers.

    Every row and every action of the workflow is checked here, before any
    record is prepared, so a bad value stops the run instead of surfacing from
    the first action that renders the row.
    """
    entries = selected_seed_entries(action_configs)
    if not entries:
        return

    where = f"{Path(file_path).parent.name}/{Path(file_path).name}"
    for index, row in _rows(raw_content):
        for action_name, entry in entries:
            try:
                entry.file_for(row, action_name)
            except SeedSelectionError as exc:
                raise ConfigValidationError(
                    f"{exc} ({where}, record {index})",
                    context={
                        "file_path": file_path,
                        "record_index": index,
                        "action_name": action_name,
                        "seed_key": entry.key,
                        "select_by": entry.select_by,
                    },
                    cause=exc,
                ) from exc


def _rows(raw_content: Any) -> list[tuple[int, Mapping[str, Any]]]:
    """The records a staged file holds, as a prompt reads them, with their positions."""
    if isinstance(raw_content, list):
        return [(i, row) for i, row in enumerate(raw_content) if isinstance(row, Mapping)]
    if isinstance(raw_content, Mapping):
        return [(0, raw_content)]
    if raw_content:
        return [(0, {"page_content": raw_content})]
    return []


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
        for idx, item in enumerate(raw_content):
            if isinstance(item, dict):
                _check_dict(item, file_path)
            else:
                logger.debug(
                    "Skipping non-dict element at index %d in %s (type: %s)",
                    idx,
                    Path(file_path).name,
                    type(item).__name__,
                )


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
