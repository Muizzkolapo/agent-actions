"""Static defect detection for action ``expect:`` blocks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

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
    workflow: str | None = None,
) -> dict[str, list[str]]:
    """Per action, defects in its expect block, as ``{action: [messages]}``.

    Validates both forms of ``expect:``: an inline ``expectations:`` list, and
    a named ``suite:`` reference. The latter is only checked when *project_root*
    and *workflow* are given, since resolving a suite file requires both.
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
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                messages.extend(_entry_defects(entry, fields))
        elif isinstance(suite_name, str) and project_root is not None and workflow is not None:
            messages.extend(_suite_defects(suite_name, project_root, workflow, fields))

        if messages:
            defects[action_name] = sorted(messages)

    return defects


def _suite_defects(
    suite_name: str, project_root: Path, workflow: str, fields: set[str] | None
) -> list[str]:
    from agent_actions.expectations.loader import SuiteNotFoundError, load_named_suite

    try:
        suite = load_named_suite(project_root, workflow, suite_name)
    except SuiteNotFoundError as exc:
        return [f"suite '{suite_name}': {exc}"]
    except (ValueError, TypeError, OSError, yaml.YAMLError) as exc:
        return [f"suite '{suite_name}' could not be loaded: {exc}"]

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
