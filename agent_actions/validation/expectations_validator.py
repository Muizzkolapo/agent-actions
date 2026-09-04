"""Static defect detection for action ``expect:`` blocks."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agent_actions.expectations import registry
from agent_actions.expectations.fields import referenced_names
from agent_actions.expectations.types import Expectation

EXPECTATIONS_REMEDY = (
    "Fix the expectation declaration: use a registered type (each defect below "
    "lists the registered ones), put the type's arguments under params:, and "
    "target a field the action's schema produces."
)

_VERDICT_KEY = "expect"


def find_expectation_defects(
    action_configs: dict[str, dict[str, Any]],
    available_fields: dict[str, set[str]],
    *,
    project_root: Path | None = None,
) -> dict[str, list[str]]:
    """Per action, defects in its expect block, as ``{action: [messages]}``.

    Validates every form of ``expect:``: an inline ``expectations:`` list, a
    named ``suite:`` reference, and a bare block that defaults to the action's
    own schema. The named and bare forms are only checked when *project_root*
    is given.
    """
    defects: dict[str, list[str]] = {}

    for action_name, action in action_configs.items():
        expect = action.get("expect")
        if not isinstance(expect, dict):
            continue

        fields = available_fields.get(action_name)
        messages: list[str] = []

        if fields is not None and _VERDICT_KEY in fields:
            messages.append(
                f"output field '{_VERDICT_KEY}' collides with the verdict key the "
                f"framework attaches; rename the schema field"
            )

        entries = expect.get("expectations")
        suite_name = expect.get("suite")
        if isinstance(entries, list):
            if not entries:
                messages.append(
                    "expectations: is an empty list; add entries, or omit the "
                    "key to read the action's own schema"
                )
            messages.extend(_entry_defects(entries, fields))
        elif isinstance(suite_name, str) and project_root is not None:
            messages.extend(_suite_defects(suite_name, project_root, fields))
        elif entries is None and suite_name is None and project_root is not None:
            messages.extend(_default_suite_defects(action, project_root, fields))

        if messages:
            defects[action_name] = sorted(messages)

    return defects


def _default_suite_defects(
    action: dict[str, Any], project_root: Path, fields: set[str] | None
) -> list[str]:
    """Defects for a bare expect: block, which reads the action's own schema.

    A named schema is inlined into the action config at load time (its name
    dropped), so the resolved dict is the authority; the name survives only
    when loading could not inline it.
    """
    from agent_actions.expectations.loader import schema_rule_entries

    schema_data = action.get("schema")
    if isinstance(schema_data, dict):
        label = schema_data.get("name") or action.get("name") or "the action's schema"
        try:
            entries, defects = schema_rule_entries(str(label), schema_data)
        except ValueError as exc:
            return [
                f"a bare expect: reads the rules of the action's own schema — {exc}; "
                f"declare them under a field or in the file's expectations: block, "
                f"or use suite: or an inline expectations: list"
            ]
        return defects + _entry_defects(entries, fields)
    schema_name = action.get("schema_name")
    if isinstance(schema_name, str) and schema_name:
        return _suite_defects(schema_name, project_root, fields)
    return [
        "a bare expect: reads the rules of the action's own schema, "
        "but this action declares no schema; add one, or use suite: or an "
        "inline expectations: list"
    ]


def _suite_defects(suite_name: str, project_root: Path, fields: set[str] | None) -> list[str]:
    from agent_actions.expectations.loader import SuiteLoadError, load_schema_rules

    try:
        entries, defects = load_schema_rules(suite_name, project_root)
    except SuiteLoadError as exc:
        return [str(exc)]

    return defects + _entry_defects(entries, fields)


def _entry_defects(entries: list[Any], fields: set[str] | None) -> list[str]:
    """Defects for raw rule entries, reported one rule at a time.

    Every source of rules — an inline list, a named suite, a schema's own
    fields — comes through here, so one bad rule never costs the rest their
    checks and every route words the same defect the same way.
    """
    messages: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            messages.append(f"expectations: entry must be a mapping, got {type(entry).__name__}")
            continue
        raw_id = entry.get("id")
        label = raw_id if isinstance(raw_id, str) and raw_id else entry.get("type") or "<unnamed>"
        try:
            expectation = Expectation.model_validate(entry)
        except ValidationError as exc:
            messages.extend(f"{label}: {_reason(err)}" for err in exc.errors())
            continue
        messages.extend(_rule_defects(expectation, fields))
    return messages


def _reason(error: Mapping[str, Any]) -> str:
    """One pydantic error as prose, naming the rule key it is about.

    Only the first location segment: a rule key is flat, and the rest are a
    union's branch tags, which name nothing an author wrote.
    """
    text = str(error.get("msg", "")).removeprefix("Value error, ")
    location = next((str(part) for part in error.get("loc", ()) if isinstance(part, str)), "")
    return f"{location}: {text}" if location else text


def _rule_defects(expectation: Expectation, fields: set[str] | None) -> list[str]:
    label = expectation.id or expectation.type
    etype = registry.get(expectation.type)
    if etype is None:
        return [
            f"{label}: unknown type '{expectation.type}'. "
            f"Known types: {', '.join(registry.known_types())}"
        ]

    messages: list[str] = []

    supplied = set(expectation.params)
    for unknown in sorted(supplied - etype.params):
        messages.append(f"{label}: type '{expectation.type}' takes no parameter '{unknown}'")
    for missing in sorted(etype.required - supplied):
        messages.append(f"{label}: type '{expectation.type}' requires parameter '{missing}'")

    selector = expectation.field
    if fields is not None and selector is not None:
        for name in referenced_names(selector):
            if name not in fields:
                messages.append(f"{label}: field '{name}' is not produced by this action")

    return messages
