"""Namespaced content utilities for the additive record model.

Each action's output is stored under its namespace in the record's
``content`` dict.  Previous actions' namespaces are preserved — nothing
is ever replaced.

Usage::

    from agent_actions.utils.content import wrap_content, read_namespace

    # Writing: action adds its output under its name
    record["content"] = wrap_content(
        action_name="summarize",
        action_output={"summary": "..."},
        existing_content=input_record.get("content", {}),
    )

    # Reading: access a specific action's output
    summary = read_namespace(record, "summarize", "summary")
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def wrap_content(
    action_name: str,
    action_output: dict[str, Any],
    existing_content: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add *action_output* under *action_name*, preserving existing namespaces.

    Returns a new dict — does not mutate *existing_content*.
    """
    content = dict(existing_content) if existing_content else {}
    content[action_name] = action_output
    return content


def read_namespace(
    record: dict[str, Any],
    action_name: str,
    field: str | None = None,
    default: Any = None,
) -> Any:
    """Read from a specific action's namespace in the record.

    If *field* is ``None``, returns the entire namespace dict.
    """
    content = record.get("content", {})
    ns = content.get(action_name)
    if ns is None:
        return default
    if field is None:
        return ns
    return ns.get(field, default)


def has_namespace(record: dict[str, Any], action_name: str) -> bool:
    """Return True if the record has output from *action_name*."""
    content = record.get("content", {})
    return action_name in content


def get_all_namespaces(record: dict[str, Any]) -> list[str]:
    """Return the list of action names that have output on this record."""
    content = record.get("content", {})
    return list(content.keys())


def is_version_merge(agent_config: Mapping[str, Any]) -> bool:
    """True when the action consumes version output (content is pre-namespaced)."""
    return bool(agent_config.get("version_consumption_config"))


def get_existing_content(record: dict[str, Any]) -> dict[str, Any]:
    """Return the existing namespaced content dict from a record.

    Returns an empty dict if the record has no content.
    """
    content = record.get("content")
    if isinstance(content, dict):
        return content
    return {}
