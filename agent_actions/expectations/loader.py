"""Building a Suite from a schema-path file or an inline list."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_actions.errors import AgentActionsError
from agent_actions.expectations import registry
from agent_actions.expectations.types import Expectation, Suite


class SuiteLoadError(ValueError):
    """A named suite could not be loaded from the schema path."""


class NoRulesDeclared(ValueError):
    """A schema file carries no rules at all, which is distinct from carrying bad ones."""


def _looks_like_rules(value: Any) -> bool:
    """Whether a value is a list of rules, rather than a member that shares the name."""
    return isinstance(value, list) and any(
        isinstance(entry, dict) and "type" in entry for entry in value
    )


def _nested_rule_owner(node: Any, name: str | None = None) -> str | None:
    """The name of the first nested member carrying rules the loader cannot reach.

    Each node is tested on the way in rather than through its parent, so a dict
    reached as an element of a list is checked like any other.
    """
    if isinstance(node, dict):
        if name is not None and _looks_like_rules(node.get("expectations")):
            return str(node.get("id") or node.get("name") or name)
        for key, value in node.items():
            found = _nested_rule_owner(value, str(key))
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _nested_rule_owner(item, name)
            if found is not None:
                return found
    return None


def _field_scoped_entries(suite_name: str, data: dict[str, Any]) -> tuple[list[Any], list[str]]:
    """Rules declared under a ``fields:`` entry, each carrying that field as its selector.

    Returns the rules and the defects of individual rules. A defective rule is
    left out rather than raised on, so a caller reporting defects can report all
    of them; the file's own structure still raises, since there is nothing to
    report rule by rule when the shape itself is wrong.
    """
    fields = data.get("fields")
    if fields is None:
        return [], []
    if not isinstance(fields, list):
        raise ValueError(
            f"Schema file '{suite_name}' has a fields: value that is not a list, "
            f"found {type(fields).__name__}"
        )

    entries: list[Any] = []
    defects: list[str] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        rules = field.get("expectations")
        field_id = field.get("id") or field.get("name")
        if rules is not None and not isinstance(rules, list):
            raise ValueError(
                f"Schema file '{suite_name}': field '{field_id}' has an expectations: "
                f"value that is not a list, found {type(rules).__name__}"
            )

        # A selector only reaches a top-level field, so rules on anything below one
        # would never run; refusing them beats dropping them silently. Checked for
        # every field, including one that carries rules of its own.
        nested = _nested_rule_owner({k: v for k, v in field.items() if k != "expectations"})
        if nested is not None:
            raise ValueError(
                f"Schema file '{suite_name}': field '{field_id}' has expectations on its "
                f"nested member '{nested}'; a selector reaches top-level fields only, so "
                f"move the rule to the field itself or write a custom check"
            )
        if not rules:
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
                label = entry.get("id") or entry.get("type") or "<unnamed>"
                defects.append(
                    f"{label}: a rule on field '{field_id}' must not declare field: — "
                    f"position already names what it tests"
                )
                continue
            if registry.is_record_scoped(str(entry.get("type"))):
                label = entry.get("id") or entry.get("type") or "<unnamed>"
                defects.append(
                    f"{label}: a rule on field '{field_id}' is type '{entry['type']}', which "
                    f"is evaluated against the whole record and takes no field; move it to "
                    f"the file's own expectations: block"
                )
                continue
            entries.append({**entry, "field": field_id})
    return entries, defects


def schema_rule_entries(suite_name: str, data: Any) -> tuple[list[Any], list[str]]:
    """Every rule a schema file declares, as raw entries with selectors stamped.

    Raises only for problems with the file's own structure, so a caller can
    report each rule's own defects one at a time instead of losing the rest to
    the first bad one.
    """
    # schema: accepts a bare list of field dicts as well as a mapping; the rules
    # hang off the fields either way.
    if isinstance(data, list):
        data = {"fields": data}
    if not isinstance(data, dict):
        raise ValueError(
            f"Schema file '{suite_name}' must be a mapping or a list of fields, "
            f"found {type(data).__name__}"
        )
    scoped, defects = _field_scoped_entries(suite_name, data)
    # Every part of the file a selector cannot reach, not just the fields: list —
    # a JSON-Schema-format file has no fields: at all, and its rules would
    # otherwise be dropped without a word.
    unreachable = _nested_rule_owner(
        {k: v for k, v in data.items() if k not in ("expectations", "fields")}
    )
    if unreachable is not None:
        raise ValueError(
            f"Schema file '{suite_name}' has expectations on '{unreachable}', which a "
            f"selector cannot reach; a rule belongs on a top-level field or in the "
            f"file's own expectations: block"
        )

    own = data.get("expectations")
    if own is not None and not isinstance(own, list):
        raise ValueError(
            f"Schema file '{suite_name}' has an expectations: value that is not a list, "
            f"found {type(own).__name__}"
        )
    entries = scoped + list(own or [])
    if not entries and not defects:
        raise NoRulesDeclared(
            f"Schema file '{suite_name}' declares no expectations: no rules on its "
            f"fields and no expectations: block"
        )
    return entries, defects


def build_suite_from_schema_data(suite_name: str, data: Any) -> Suite:
    """Build a Suite from a schema file's rules, on its fields or in its own block."""
    entries, defects = schema_rule_entries(suite_name, data)
    if defects:
        raise ValueError(f"Schema file '{suite_name}': " + "; ".join(defects))
    return Suite(name=suite_name, expectations=entries)


def _load_schema_data(suite_name: str, project_root: Path | None) -> Any:
    """Read a suite's file through the schema route, as one named error on failure."""
    from agent_actions.output.response.loader import SchemaLoader

    try:
        return SchemaLoader.load_schema(suite_name, project_root=project_root)
    except FileNotFoundError as exc:
        raise SuiteLoadError(f"suite '{suite_name}': {exc}") from exc
    except (OSError, ValueError, TypeError, yaml.YAMLError, AgentActionsError) as exc:
        raise SuiteLoadError(f"suite '{suite_name}' could not be loaded: {exc}") from exc


def load_named_suite(suite_name: str, project_root: Path | None = None) -> Suite:
    """Load a suite by name through the schema route, like ``schema:`` resolves.

    Every failure — missing file, unreadable file, or a file without a usable
    ``expectations:`` block — raises :class:`SuiteLoadError` naming the suite,
    so callers classify one error instead of the schema route's surface.
    """
    data = _load_schema_data(suite_name, project_root)
    try:
        return build_suite_from_schema_data(suite_name, data)
    except ValueError as exc:
        raise SuiteLoadError(f"suite '{suite_name}' could not be loaded: {exc}") from exc


def load_schema_rules(
    suite_name: str, project_root: Path | None = None
) -> tuple[list[Any], list[str]]:
    """The raw rule entries of a named suite, for callers that report per rule."""
    data = _load_schema_data(suite_name, project_root)
    try:
        return schema_rule_entries(suite_name, data)
    except ValueError as exc:
        raise SuiteLoadError(f"suite '{suite_name}' could not be loaded: {exc}") from exc


def build_inline_suite(entries: list[dict[str, Any]], action_name: str) -> Suite:
    """Wrap an action's inline ``expectations:`` list as an anonymous suite."""
    return Suite(
        name=f"{action_name}:inline", expectations=[Expectation(**entry) for entry in entries]
    )
