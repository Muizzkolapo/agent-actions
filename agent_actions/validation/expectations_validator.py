"""Static defect detection for action ``expect:`` blocks."""

from __future__ import annotations

from typing import Any

from agent_actions.expectations import registry
from agent_actions.expectations.fields import referenced_names

EXPECTATIONS_REMEDY = (
    "Fix the expectation declaration: use a registered type "
    "(agac expect list shows them), pass only that type's parameters, and target "
    "a field the action's schema produces."
)

_DECLARED_KEYS = frozenset({"id", "type", "field", "severity", "hint"})
_VERDICT_KEY = "expect"


def find_expectation_defects(
    action_configs: dict[str, dict[str, Any]],
    available_fields: dict[str, set[str]],
) -> dict[str, list[str]]:
    """Per action, defects in its expect block, as ``{action: [messages]}``."""
    defects: dict[str, list[str]] = {}

    for action_name, action in action_configs.items():
        expect = action.get("expect")
        if not isinstance(expect, dict):
            continue

        entries = expect.get("expectations")
        if not isinstance(entries, list):
            continue

        fields = available_fields.get(action_name)
        messages: list[str] = []

        if fields and _VERDICT_KEY in fields:
            messages.append(
                f"output field '{_VERDICT_KEY}' collides with the verdict key the "
                f"framework attaches; rename the schema field"
            )

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            messages.extend(_entry_defects(entry, fields))

        if messages:
            defects[action_name] = sorted(messages)

    return defects


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
    if fields and selector is not None:
        for name in referenced_names(selector):
            if name not in fields:
                messages.append(f"{label}: field '{name}' is not produced by this action")

    return messages
