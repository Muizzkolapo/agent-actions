"""Namespaced content utilities for the additive record model.

Each action's output is stored under its namespace in the record's
``content`` dict.  Previous actions' namespaces are preserved — nothing
is ever replaced.  Content is written via ``RecordEnvelope.build_content``
and read via ``get_existing_content``.

A version-merge tool is the exception: its output is spread flat, so its field
names are content's own keys and one already taken does replace it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from agent_actions.utils.constants import RUNTIME_BUS_NAMESPACES

logger = logging.getLogger(__name__)


def is_version_merge(agent_config: Mapping[str, Any]) -> bool:
    """True when the action consumes version output (content is pre-namespaced)."""
    return bool(agent_config.get("version_consumption_config"))


def merge_version_content(
    existing_content: Mapping[str, Any] | None,
    action_output: Mapping[str, Any],
    action_name: str,
) -> dict[str, Any]:
    """Spread a version-merge tool's output flat over *existing_content*, reporting replacements.

    The output wins, a framework namespace included: such a field is the tool's own data
    and a guard reading it must keep finding it, so dropping it here would trade a lost
    namespace for a clause that reads a missing field and silently filters the record.
    That name is refused where an action declares it instead.
    """
    merged = dict(existing_content or {})
    for key, value in action_output.items():
        if key in merged:
            logger.warning(
                "Action '%s': output field '%s' replaces the existing '%s' namespace "
                "in record content%s",
                action_name,
                key,
                key,
                (
                    " — a framework namespace, whose loss the framework cannot replace"
                    if key in RUNTIME_BUS_NAMESPACES
                    else ""
                ),
            )
        merged[key] = value
    return merged


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
