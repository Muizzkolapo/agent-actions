"""Static defect detection for action ``expect:`` blocks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_actions.expectations import registry
from agent_actions.expectations.fields import referenced_names
from agent_actions.expectations.types import _DECLARED_FIELDS as _DECLARED_KEYS

EXPECTATIONS_REMEDY = (
    "Fix the expectation declaration: use a registered type "
    "(agac expect list shows them), pass only that type's parameters, and target "
    "a field the action's schema produces."
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
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                messages.extend(_entry_defects(entry, fields))
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
    schema_data = action.get("schema")
    if isinstance(schema_data, dict):
        entries = schema_data.get("expectations")
        if not isinstance(entries, list) or not entries:
            return [
                "a bare expect: reads the expectations: block of the action's "
                "schema, which has no expectations; add the block to the schema "
                "file, or use suite: or an inline expectations: list"
            ]
        messages: list[str] = []
        for entry in entries:
            if isinstance(entry, dict):
                messages.extend(_entry_defects(entry, fields))
        return messages
    schema_name = action.get("schema_name")
    if isinstance(schema_name, str) and schema_name:
        return _suite_defects(schema_name, project_root, fields)
    return [
        "a bare expect: reads the expectations: block of the action's schema, "
        "but this action declares no schema; add one, or use suite: or an "
        "inline expectations: list"
    ]


def _suite_defects(suite_name: str, project_root: Path, fields: set[str] | None) -> list[str]:
    from agent_actions.expectations.loader import SuiteLoadError, load_named_suite

    try:
        suite = load_named_suite(suite_name, project_root)
    except SuiteLoadError as exc:
        return [str(exc)]

    messages: list[str] = []
    for expectation in suite.expectations:
        messages.extend(_entry_defects(expectation.model_dump(exclude_none=True), fields))
    return messages


def _entry_defects(entry: dict[str, Any], fields: set[str] | None) -> list[str]:
    label = entry.get("id") or entry.get("type") or "<unnamed>"
    type_name = entry.get("type")

    etype = registry.get(type_name) if isinstance(type_name, str) else None
    if etype is None:
        return [
            f"{label}: unknown type '{type_name}'. Known types: {', '.join(registry.known_types())}"
        ]

    messages: list[str] = []

    supplied = {k for k in entry if k not in _DECLARED_KEYS}
    for unknown in sorted(supplied - etype.params):
        messages.append(f"{label}: type '{type_name}' takes no parameter '{unknown}'")
    for missing in sorted(etype.required - supplied):
        messages.append(f"{label}: type '{type_name}' requires parameter '{missing}'")

    selector = entry.get("field")
    if fields is not None and selector is not None:
        if not isinstance(selector, (str, list)):
            messages.append(
                f"{label}: field must be a string or list of strings, got {type(selector).__name__}"
            )
        else:
            for name in referenced_names(selector):
                if name not in fields:
                    messages.append(f"{label}: field '{name}' is not produced by this action")

    return messages
