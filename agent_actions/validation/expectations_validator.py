"""Static defect detection for action ``expect:`` blocks."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agent_actions.expectations import registry
from agent_actions.expectations.expression import (
    ExpressionParseError,
    parse_condition,
    referenced_field_paths,
)
from agent_actions.expectations.fields import referenced_names
from agent_actions.expectations.types import Expectation

EXPECTATIONS_REMEDY = (
    "Fix the expect: block — each defect names its correction. For "
    "type/parameter/field defects: use a registered type (each unknown-type "
    "defect lists the registered ones), put the type's arguments under params:, "
    "and target a field the action's schema produces."
)

from agent_actions.utils.constants import VERDICT_KEY as _VERDICT_KEY


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
        resolved: list[Any] = []
        if isinstance(entries, list):
            if not entries:
                messages.append(
                    "expectations: is an empty list; add entries, or omit the "
                    "key to read the action's own schema"
                )
            resolved = entries
            messages.extend(_entry_defects(entries, fields, available_fields))
        elif isinstance(suite_name, str) and project_root is not None:
            resolved, suite_messages = _named_suite_entries(suite_name, project_root)
            messages.extend(suite_messages)
            messages.extend(_entry_defects(resolved, fields, available_fields))
        elif entries is None and suite_name is None and project_root is not None:
            resolved, schema_messages = _own_schema_entries(action, project_root)
            messages.extend(schema_messages)
            messages.extend(_entry_defects(resolved, fields, available_fields))

        # Runs against the resolved rules, so the execution-shape checks see the
        # same rules the runner will, wherever they were declared.
        messages.extend(_repair_mode_defects(action, expect, resolved))

        if messages:
            defects[action_name] = sorted(messages)

    return defects


def _config_token(value: Any) -> str:
    """Normalize a config value that may be an enum member or a cased string."""
    raw = getattr(value, "value", value)
    return str(raw).lower() if raw is not None else ""


def _repair_mode_defects(
    action: dict[str, Any], expect: dict[str, Any], entries: list[Any]
) -> list[str]:
    """Defects for the repair-loop keys against the action's execution shape."""
    messages: list[str] = []
    is_batch = _config_token(action.get("run_mode")) == "batch"
    if is_batch:
        # Batch validates from the stored result and has no llm_context, so a
        # judged rule with context: refs would fail every record on a missing
        # context source rather than on its own rule.
        for entry in entries:
            if (
                isinstance(entry, dict)
                and entry.get("type") == "llm_judge"
                and isinstance(entry.get("params"), dict)
                and entry["params"].get("context")
            ):
                label = entry.get("id") or entry.get("type")
                messages.append(
                    f"{label}: context: refs are not available under batch run_mode — "
                    "the judge would fail every record on a missing context source; "
                    "drop context: or run the action online"
                )
    repair = expect.get("repair", "auto")
    if repair == "none":
        return messages
    if is_batch:
        messages.append(
            f"repair: {repair} is not supported under batch run_mode — the batch "
            "path validates and reports but does not regenerate; use repair: none "
            "or run the action online"
        )
        return messages
    if isinstance(repair, dict):
        messages.append("repair: {prompt:} is not implemented; use retry or auto")
        return messages
    from agent_actions.processing.helpers import _is_tool_action

    if _is_tool_action(action):
        messages.append(
            f"repair: {repair} cannot run on a tool action — re-running a "
            "deterministic UDF yields the same output; use repair: none"
        )
    if _config_token(action.get("granularity")) == "file":
        messages.append(
            f"repair: {repair} cannot run at file granularity — one call "
            "produces the whole file, so a single failing record would "
            "regenerate all of them; use repair: none or record granularity"
        )
    schema = action.get("schema")
    if schema is not None and not isinstance(schema, dict):
        messages.append(
            f"repair: {repair} found a non-mapping schema ({type(schema).__name__}); "
            "the structural gate would silently check record shape only — fix the schema"
        )
    elif schema is None and action.get("schema_name"):
        messages.append(
            f"repair: {repair} declared, but the named schema "
            f"'{action['schema_name']}' was not inlined — the structural gate "
            "would silently check record shape only; fix the schema reference"
        )
    return messages


def _own_schema_entries(
    action: dict[str, Any], project_root: Path | None
) -> tuple[list[Any], list[str]]:
    """The rules a bare expect: reads, which are the action's own schema's.

    A named schema is inlined into the action config at load time (its name
    dropped), so the resolved dict is the authority; the name survives only
    when loading could not inline it.
    """
    from agent_actions.expectations.loader import NoRulesDeclared, schema_rule_entries

    schema_data = action.get("schema")
    if isinstance(schema_data, (dict, list)):
        label = (
            (schema_data.get("name") if isinstance(schema_data, dict) else None)
            or action.get("name")
            or "the action's schema"
        )
        try:
            entries, defects = schema_rule_entries(str(label), schema_data)
        except NoRulesDeclared as exc:
            return [], [
                f"a bare expect: reads the rules of the action's own schema — {exc}; "
                f"declare them under a field or in the file's expectations: block, "
                f"or use suite: or an inline expectations: list"
            ]
        except ValueError as exc:
            # The file has rules; they are in the wrong place or the wrong shape,
            # so the advice for a file with none would contradict the message.
            return [], [f"a bare expect: reads the rules of the action's own schema — {exc}"]
        return entries, defects
    schema_name = action.get("schema_name")
    if isinstance(schema_name, str) and schema_name:
        return _named_suite_entries(schema_name, project_root)
    return [], [
        "a bare expect: reads the rules of the action's own schema, "
        "but this action declares no schema; add one, or use suite: or an "
        "inline expectations: list"
    ]


def _named_suite_entries(suite_name: str, project_root: Path | None) -> tuple[list[Any], list[str]]:
    """The rules of a named suite, or the one error that stopped it loading."""
    from agent_actions.expectations.loader import SuiteLoadError, load_schema_rules

    try:
        return load_schema_rules(suite_name, project_root)
    except SuiteLoadError as exc:
        return [], [str(exc)]


def _entry_defects(
    entries: list[Any], fields: set[str] | None, all_fields: dict[str, set[str]]
) -> list[str]:
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

        # The type first: the model's own rules are about a rule's shape, and a
        # shape complaint about a type that does not exist sends the author the
        # wrong way.
        type_name = entry.get("type")
        etype = registry.get(type_name) if isinstance(type_name, str) else None
        if etype is None:
            messages.append(
                f"{label}: unknown type '{type_name}'. "
                f"Known types: {', '.join(registry.known_types())}"
            )
            continue
        selector = entry.get("field")
        if selector is not None and not isinstance(selector, (str, list)):
            # Pydantic reports this as one message per union branch, naming
            # neither the shape wanted nor the type found.
            messages.append(
                f"{label}: field must be a string or list of strings, got {type(selector).__name__}"
            )
            messages.extend(_argument_defects(label, etype, entry.get("params")))
            continue
        try:
            expectation = Expectation.model_validate(entry)
        except ValidationError as exc:
            messages.extend(f"{label}: {_reason(err)}" for err in exc.errors())
            # The shape is wrong, but the arguments are a separate question and
            # the author should not have to fix one to see the other.
            messages.extend(_argument_defects(label, etype, entry.get("params")))
            continue
        messages.extend(_rule_defects(expectation, fields, all_fields))
    return messages


def _reason(error: Mapping[str, Any]) -> str:
    """One pydantic error as prose, naming the rule key it is about.

    Only the first location segment: a rule key is flat, and the rest are a
    union's branch tags, which name nothing an author wrote.
    """
    text = str(error.get("msg", "")).removeprefix("Value error, ")
    location = next((str(part) for part in error.get("loc", ()) if isinstance(part, str)), "")
    return f"{location}: {text}" if location else text


def _argument_defects(label: str, etype: Any, params: Any) -> list[str]:
    """Defects in a rule's arguments, independent of anything else about the rule."""
    supplied = set(params) if isinstance(params, dict) else set()
    return [
        f"{label}: type '{etype.name}' takes no parameter '{unknown}'"
        for unknown in sorted(supplied - etype.params)
    ] + [
        f"{label}: type '{etype.name}' requires parameter '{missing}'"
        for missing in sorted(etype.required - supplied)
    ]


def _rule_defects(
    expectation: Expectation, fields: set[str] | None, all_fields: dict[str, set[str]]
) -> list[str]:
    label = expectation.id or expectation.type
    etype = registry.get(expectation.type)
    if etype is None:
        return [
            f"{label}: unknown type '{expectation.type}'. "
            f"Known types: {', '.join(registry.known_types())}"
        ]

    messages = _argument_defects(label, etype, expectation.params)

    if "row_condition" in expectation.params:
        messages.extend(
            _expression_defects(
                f"{label}: row_condition", expectation.params["row_condition"], fields
            )
        )

    selector = expectation.field
    if expectation.type == "expression":
        # Only when supplied: an absent condition is already the missing-parameter defect.
        if "condition" in expectation.params:
            messages.extend(_expression_defects(label, expectation.params["condition"], fields))
    elif selector is not None and len(selector) == 0:
        messages.append(f"{label}: field must not be empty")
    elif fields is not None and selector is not None:
        for name in referenced_names(selector):
            if name not in fields:
                messages.append(f"{label}: field '{name}' is not produced by this action")

    if expectation.type == "llm_judge" and "votes" in expectation.params:
        votes = expectation.params["votes"]
        if not isinstance(votes, int) or isinstance(votes, bool) or votes < 1:
            messages.append(f"{label}: votes must be a positive integer, got {votes!r}")

    if expectation.type == "llm_judge" and "context" in expectation.params:
        context_refs = expectation.params["context"]
        if not isinstance(context_refs, list):
            messages.append(
                f"{label}: context must be a list of 'action.field' strings, "
                f"got {type(context_refs).__name__}"
            )
        else:
            for ref in context_refs:
                if not isinstance(ref, str) or "." not in ref:
                    messages.append(f"{label}: context reference '{ref}' must be 'action.field'")
                    continue
                ref_action, _, ref_field = ref.partition(".")
                ref_fields = all_fields.get(ref_action)
                if ref_fields is None:
                    messages.append(
                        f"{label}: context reference '{ref}' names unknown action '{ref_action}'"
                    )
                elif ref_field not in ref_fields:
                    messages.append(
                        f"{label}: context reference '{ref}' — action '{ref_action}' "
                        f"does not produce field '{ref_field}'"
                    )

    return messages


def _expression_defects(label: str, condition: Any, fields: set[str] | None) -> list[str]:
    if not isinstance(condition, str) or not condition.strip():
        return [f"{label}: condition must be a non-empty string, got {condition!r}"]
    try:
        ast = parse_condition(condition)
    except ExpressionParseError as exc:
        return [f"{label}: {exc}"]
    paths = referenced_field_paths(ast.root)
    if not paths:
        return [
            f"{label}: condition references no record fields, so it always evaluates the same way"
        ]
    if fields is None:
        return []
    messages = []
    for path in paths:
        top_segment = path.split(".", 1)[0]
        if top_segment not in fields:
            messages.append(
                f"{label}: condition references '{path}' but this action "
                f"does not produce field '{top_segment}'"
            )
    return messages
