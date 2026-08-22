"""Resolving an expectation's ``field:`` selector against a record."""

from __future__ import annotations

from typing import Any

WILDCARD_SUFFIX = "[*]"


class FieldResolutionError(Exception):
    """Raised when a selector names something the record does not provide."""


def resolve(record: dict[str, Any], selector: str | list[str]) -> list[Any]:
    """Return one check input per value the selector selects.

    A bare name yields a single input holding the whole value, so a check that
    needs the entire array (``item_count``, ``word_count_ratio``) receives it.
    A ``name[*]`` selector yields one input per element, so a per-element check
    runs once per element. A list of names yields a single input that is the
    list of their values, for checks spanning several fields.
    """
    if isinstance(selector, list):
        return [[_lookup(record, name) for name in selector]]

    if selector.endswith(WILDCARD_SUFFIX):
        base = selector[: -len(WILDCARD_SUFFIX)]
        value = _lookup(record, base)
        if not isinstance(value, list):
            raise FieldResolutionError(
                f"Selector '{selector}' needs a list at '{base}', found {type(value).__name__}"
            )
        return list(value)

    return [_lookup(record, selector)]


def referenced_names(selector: str | list[str]) -> list[str]:
    """The record keys a selector reads, for preflight schema checks."""
    if isinstance(selector, list):
        return list(selector)
    if selector.endswith(WILDCARD_SUFFIX):
        return [selector[: -len(WILDCARD_SUFFIX)]]
    return [selector]


def resolve_context(llm_context: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    """Resolve a judged expectation's ``context:`` refs against ``llm_context``.

    Each ref uses the same ``action.field`` syntax ``context_scope.observe``
    already uses. ``llm_context`` is nested one level by action name, unlike
    a record's own flat fields, so this does not reuse ``_lookup``.
    """
    resolved: dict[str, Any] = {}
    for ref in refs:
        action_name, sep, field_name = ref.partition(".")
        if not sep:
            raise FieldResolutionError(f"context reference '{ref}' must be 'action.field'")
        action_data = llm_context.get(action_name)
        if not isinstance(action_data, dict) or field_name not in action_data:
            raise FieldResolutionError(f"context reference '{ref}' is not present in llm_context")
        resolved[ref] = action_data[field_name]
    return resolved


def _lookup(record: dict[str, Any], name: str) -> Any:
    if name not in record:
        raise FieldResolutionError(f"Field '{name}' is not present in the record")
    return record[name]
