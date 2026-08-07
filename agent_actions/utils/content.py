"""Namespaced content utilities for the additive record model.

Each action's output is stored under its namespace in the record's
``content`` dict.  Previous actions' namespaces are preserved — nothing
is ever replaced.  Content is written via ``RecordEnvelope.build_content``
and read via ``get_existing_content``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def is_version_merge(agent_config: Mapping[str, Any]) -> bool:
    """True when the action consumes version output (content is pre-namespaced)."""
    return bool(agent_config.get("version_consumption_config"))


def get_existing_content(
    record: dict[str, Any],
    *,
    is_first_stage: bool = False,
) -> dict[str, Any]:
    """Return existing namespaced content, synthesizing source for first-stage.

    This is the SINGLE function for content extraction — batch and online
    paths both use this. Never bypass with raw record.get("content").
    """
    content = record.get("content")
    if isinstance(content, dict):
        return content
    if is_first_stage:
        from agent_actions.record.envelope import RECORD_FRAMEWORK_FIELDS

        raw = {k: v for k, v in record.items() if k not in RECORD_FRAMEWORK_FIELDS}
        if raw:
            return {"source": raw}
    return {}
