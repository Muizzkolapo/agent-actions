"""Building a Suite from a schema-path file or an inline list."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_actions.errors import AgentActionsError
from agent_actions.expectations.types import Expectation, Suite


class SuiteLoadError(ValueError):
    """A named suite could not be loaded from the schema path."""


def _nested_rule_owner(node: Any) -> str | None:
    """The name of the first nested member carrying rules the loader cannot reach."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, dict) and value.get("expectations"):
                return str(key)
            found = _nested_rule_owner(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _nested_rule_owner(item)
            if found is not None:
                return found
    return None


def _field_scoped_entries(suite_name: str, data: dict[str, Any]) -> list[Any]:
    """Rules declared under a ``fields:`` entry, each carrying that field as its selector."""
    fields = data.get("fields")
    if fields is None:
        return []
    if not isinstance(fields, list):
        raise ValueError(
            f"Schema file '{suite_name}' has a fields: value that is not a list, "
            f"found {type(fields).__name__}"
        )

    entries: list[Any] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        rules = field.get("expectations")
        field_id = field.get("id") or field.get("name")
        if not rules:
            # A selector only reaches a top-level field, so rules on anything below
            # one would never run; refusing them beats dropping them silently.
            nested = _nested_rule_owner({k: v for k, v in field.items() if k != "expectations"})
            if nested is not None:
                raise ValueError(
                    f"Schema file '{suite_name}': field '{field_id}' has expectations on its "
                    f"nested member '{nested}'; a selector reaches top-level fields only, so "
                    f"move the rule to the field itself or write a custom check"
                )
            continue
        if not field_id:
            raise ValueError(
                f"Schema file '{suite_name}' declares expectations on a field with no id"
            )
        for entry in rules:
            if not isinstance(entry, dict):
                entries.append(entry)
                continue
            if "field" in entry:
                raise ValueError(
                    f"Schema file '{suite_name}': the rule on field '{field_id}' must not "
                    f"declare field: — position already names what it tests"
                )
            entries.append({**entry, "field": field_id})
    return entries


def build_suite_from_schema_data(suite_name: str, data: Any) -> Suite:
    """Build a Suite from a schema file's rules, on its fields or in its own block."""
    if not isinstance(data, dict):
        raise ValueError(
            f"Schema file '{suite_name}' must be a mapping, found {type(data).__name__}"
        )
    entries = _field_scoped_entries(suite_name, data) + list(data.get("expectations") or [])
    if not entries:
        raise ValueError(
            f"Schema file '{suite_name}' declares no expectations: no rules on its "
            f"fields and no expectations: block"
        )
    return Suite(name=suite_name, expectations=entries)


def load_named_suite(suite_name: str, project_root: Path | None = None) -> Suite:
    """Load a suite by name through the schema route, like ``schema:`` resolves.

    Every failure — missing file, unreadable file, or a file without a usable
    ``expectations:`` block — raises :class:`SuiteLoadError` naming the suite,
    so callers classify one error instead of the schema route's surface.
    """
    from agent_actions.output.response.loader import SchemaLoader

    try:
        data = SchemaLoader.load_schema(suite_name, project_root=project_root)
    except FileNotFoundError as exc:
        raise SuiteLoadError(f"suite '{suite_name}': {exc}") from exc
    except (OSError, ValueError, TypeError, yaml.YAMLError, AgentActionsError) as exc:
        raise SuiteLoadError(f"suite '{suite_name}' could not be loaded: {exc}") from exc
    try:
        return build_suite_from_schema_data(suite_name, data)
    except ValueError as exc:
        raise SuiteLoadError(f"suite '{suite_name}' could not be loaded: {exc}") from exc


def build_inline_suite(entries: list[dict[str, Any]], action_name: str) -> Suite:
    """Wrap an action's inline ``expectations:`` list as an anonymous suite."""
    return Suite(
        name=f"{action_name}:inline", expectations=[Expectation(**entry) for entry in entries]
    )
