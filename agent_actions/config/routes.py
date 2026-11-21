"""Expand the route and join entries of a workflow into ordinary actions.

``- route: <name>`` becomes a built-in ``route`` tool action that writes each record's
case, and every entry action of a case gets a guard on that case which sends the other
records elsewhere. ``- join: <name>`` becomes a built-in ``pick`` tool action that
gathers them back: it writes the output of the branch each record went through.
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from agent_actions.config.includes import Inclusion
from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.tools.builtin import (
    BUILTIN_KEY,
    CASE_FIELD,
    DEFAULT_CASE,
    PICK,
    ROUTE,
    builtin_tool,
)
from agent_actions.record.elsewhere import GATHERS_KEY, SENDS_ELSEWHERE_KEY

ROUTE_KEYS = ("route", "on", "cases", "default")
JOIN_KEYS = ("join", "of")
FILTER = "filter"
ROUTE_IMPL = "agac.route"
PICK_IMPL = "agac.pick"
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
_VERSION_SUFFIX = re.compile(r"_\d+\Z")
_UNQUOTABLE = re.compile(r'["\\\x00-\x1f]')

logger = logging.getLogger(__name__)


def is_route(entry: Any) -> bool:
    return isinstance(entry, dict) and "route" in entry and "name" not in entry


def is_join(entry: Any) -> bool:
    return isinstance(entry, dict) and "join" in entry and "name" not in entry


def has_route_or_join(data: Any) -> bool:
    actions = data.get("actions") if isinstance(data, dict) else None
    return isinstance(actions, list) and any(is_route(e) or is_join(e) for e in actions)


def expand_routes(data: Any, workflow_file: str, inclusions: Sequence[Inclusion] = ()) -> Any:
    """*data* with each route and join entry replaced by the actions it stands for."""
    if not has_route_or_join(data):
        return data
    data = copy.deepcopy(data)
    entries: list[Any] = data["actions"]
    actions: dict[str, dict[str, Any]] = {
        e["name"]: e for e in entries if isinstance(e, dict) and isinstance(e.get("name"), str)
    }
    instances = {inclusion.instance: inclusion for inclusion in inclusions}
    taken = set(actions)
    expanded: list[Any] = []
    routers: list[dict[str, Any]] = []
    for entry in entries:
        if is_route(entry):
            router = _router(entry, workflow_file, actions, instances, taken)
            routers.append(router)
            expanded.append(router)
            # A later entry can name it in on:, cases:, default: or of:.
            actions[router["name"]] = router
        elif is_join(entry):
            join = _join(entry, workflow_file, actions, instances, taken)
            expanded.append(join)
            actions[join["name"]] = join
        else:
            expanded.append(entry)
    data["actions"] = expanded
    by_name = {
        a["name"]: a for a in expanded if isinstance(a, dict) and isinstance(a.get("name"), str)
    }
    for router in routers:
        _guard_entries(router, by_name)
    for router in routers:
        _refuse_cross_case_reads(router, by_name, workflow_file)
    _warn_partial_joins(routers, by_name, workflow_file)
    return data


def finish_routes(data: Any, workflow_file: str) -> None:
    """Check each router's cases against its field's ``enum`` and give each join its schema.

    Runs once the schemas are compiled into the actions.
    """
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list):
        return
    by_name = {
        a["name"]: a for a in actions if isinstance(a, dict) and isinstance(a.get("name"), str)
    }
    for action in by_name.values():
        spec = builtin_tool(action)
        if spec is None:
            continue
        if spec["tool"] == ROUTE:
            _check_cases_against_enum(action, spec, by_name, workflow_file)
        elif spec["tool"] == PICK and not action.get("schema"):
            action["schema"] = _joined_schema(action["name"], spec["of"], by_name)


# -- route -------------------------------------------------------------------


def _router(
    entry: dict[Any, Any],
    workflow_file: str,
    actions: Mapping[str, dict[str, Any]],
    instances: Mapping[str, Inclusion],
    taken: set[str],
) -> dict[str, Any]:
    name = _entry_name(entry, "route", workflow_file, taken)
    where = f"Route '{name}' in {workflow_file}"
    # YAML 1.1 reads a bare `on` key as the boolean true.
    keys = {"on" if key is True else key for key in entry}
    _refuse_unknown_keys(keys, ROUTE_KEYS, where)
    on = entry.get("on", entry.get(True))
    field_action = _field_action(on, where, actions)
    cases_raw = entry.get("cases")
    if not isinstance(cases_raw, dict) or not cases_raw:
        raise ConfigurationError(
            f"{where}: 'cases:' must map each value of {on} to the branch it enters.",
            context={"route": name},
        )
    if "default" not in entry:
        raise ConfigurationError(
            f"{where}: 'default:' is required: name the branch a record whose value has no "
            f"case enters, or write 'default: {FILTER}' to filter such a record here.",
            context={"route": name},
        )
    branches: dict[str, list[str]] = {}
    for value, target in cases_raw.items():
        case = _case_value(value, where)
        branches[case] = _branch_entries(target, f"{where}: case '{case}'", actions, instances)
    default = entry["default"]
    has_default = default != FILTER
    if has_default:
        branches[DEFAULT_CASE] = _branch_entries(
            default, f"{where}: 'default:'", actions, instances
        )
    _refuse_overlap(branches, where)
    for case, members in branches.items():
        for member in members:
            _refuse_bad_entry(member, case, field_action, actions, where)
    cases = [case for case in branches if case != DEFAULT_CASE]
    router: dict[str, Any] = {
        "name": name,
        "kind": "tool",
        "impl": ROUTE_IMPL,
        "intent": f"Route each record by {on}",
        "schema": {
            "name": f"{name}_case",
            "fields": [{"id": CASE_FIELD, "type": "string", "enum": list(branches)}],
            "additionalProperties": False,
        },
        "context_scope": {"observe": [on]},
        BUILTIN_KEY: {
            "tool": ROUTE,
            "field": on,
            "cases": cases,
            "default": has_default,
            "branches": {**branches, **({} if has_default else {DEFAULT_CASE: FILTER})},
        },
    }
    if field_action != "source":
        router["dependencies"] = [field_action]
    if not has_default:
        listed = ", ".join(f'"{case}"' for case in cases)
        router["guard"] = {
            "condition": f"{on} IN [{listed}]",
            "on_false": "filter",
            "passthrough_on_error": False,
        }
    return router


def _field_action(on: Any, where: str, actions: Mapping[str, dict[str, Any]]) -> str:
    parts = on.split(".") if isinstance(on, str) else []
    if len(parts) != 2 or not all(_NAME.match(part) for part in parts):
        raise ConfigurationError(
            f"{where}: 'on:' must name one field of one action, as <action>.<field>; got {on!r}.",
            context={"on": on},
        )
    if parts[0] != "source" and parts[0] not in actions:
        raise ConfigurationError(
            f"{where}: 'on: {on}' reads '{parts[0]}', which is no action of the workflow.",
            context={"on": on},
        )
    return parts[0]


def _case_value(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ConfigurationError(
            f"{where}: case {value!r} is not a string. A router matches string values only, "
            "so its field must hold strings.",
            context={"case": repr(value)},
        )
    if not value or _UNQUOTABLE.search(value):
        raise ConfigurationError(
            f"{where}: case {value!r} is empty or holds a quote, a backslash or a control "
            "character, which a case value cannot hold.",
            context={"case": value},
        )
    if value == DEFAULT_CASE:
        raise ConfigurationError(
            f"{where}: '{DEFAULT_CASE}' cannot be a case: it names the default branch. "
            "Map the value with 'default:' instead.",
            context={"case": value},
        )
    return value


def _branch_entries(
    target: Any,
    where: str,
    actions: Mapping[str, dict[str, Any]],
    instances: Mapping[str, Inclusion],
) -> list[str]:
    """The entry actions *target* names: actions, or the first actions of include instances."""
    names = [target] if isinstance(target, str) else target
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        raise ConfigurationError(
            f"{where} names no branch: map it to an include instance or to a list of the "
            "actions that start its branch.",
            context={"target": repr(target)},
        )
    entries: list[str] = []
    for name in names:
        if name in instances:
            entries.extend(_first_actions(instances[name]))
        elif name in actions:
            entries.append(name)
        else:
            raise ConfigurationError(
                f"{where} names '{name}', which is no action or include instance of the workflow.",
                context={"target": name},
            )
    return list(dict.fromkeys(entries))


def _first_actions(inclusion: Inclusion) -> list[str]:
    """The actions of an include instance that read no other action of it."""
    members = {action["name"] for action in inclusion.actions}
    first = []
    for action in inclusion.actions:
        dependencies = action.get("dependencies") or []
        if isinstance(dependencies, str):
            dependencies = [dependencies]
        if not members.intersection(dependencies):
            first.append(action["name"])
    return first


def _refuse_overlap(branches: Mapping[str, list[str]], where: str) -> None:
    seen: dict[str, str] = {}
    for case, members in branches.items():
        for member in members:
            if member in seen:
                raise ConfigurationError(
                    f"{where}: '{member}' starts the branch of case '{seen[member]}' and of "
                    f"case '{case}'. A record enters one branch only.",
                    context={"action_name": member},
                )
            seen[member] = case


def _refuse_bad_entry(
    member: str,
    case: str,
    field_action: str,
    actions: Mapping[str, dict[str, Any]],
    where: str,
) -> None:
    action = actions[member]
    if member == field_action:
        raise ConfigurationError(
            f"{where}: case '{case}' starts at '{member}', the action whose field the router "
            "reads.",
            context={"action_name": member},
        )
    if action.get("guard") is not None or action.get("conditional_clause") is not None:
        raise ConfigurationError(
            f"{where}: '{member}', which starts the branch of case '{case}', has a guard of "
            "its own. The router gives it the guard of its case; move the condition to the "
            "next action of the branch.",
            context={"action_name": member},
        )


def _guard_entries(router: dict[str, Any], by_name: dict[str, dict[str, Any]]) -> None:
    name = router["name"]
    for case, members in router[BUILTIN_KEY]["branches"].items():
        if members == FILTER:
            continue
        for member in members:
            action = by_name[member]
            action["guard"] = {"condition": f'{name}.case == "{case}"', "on_false": "filter"}
            action[SENDS_ELSEWHERE_KEY] = True
            dependencies = action.get("dependencies") or []
            if isinstance(dependencies, str):
                dependencies = [dependencies]
            if name not in dependencies:
                action["dependencies"] = [*dependencies, name]
            scope = action.get("context_scope")
            scope = dict(scope) if isinstance(scope, dict) else {}
            observe = scope.get("observe") or []
            reads = f"{name}.{CASE_FIELD}"
            if reads not in observe and f"{name}.*" not in observe:
                scope["observe"] = [*observe, reads]
            action["context_scope"] = scope


def _reads_of(action: dict[str, Any]) -> set[str]:
    reads: set[str] = set()
    dependencies = action.get("dependencies") or []
    reads.update([dependencies] if isinstance(dependencies, str) else dependencies)
    scope = action.get("context_scope")
    if isinstance(scope, dict):
        for directive in ("observe", "passthrough", "drop"):
            refs = scope.get(directive) or []
            reads.update(ref.split(".", 1)[0] for ref in refs if isinstance(ref, str))
    return {read for read in reads if isinstance(read, str)}


def _refuse_cross_case_reads(
    router: dict[str, Any], by_name: Mapping[str, dict[str, Any]], workflow_file: str
) -> None:
    """Refuse an action reading the branches of two cases of one router, short of a join."""
    readers: dict[str, set[str]] = {}
    for name, action in by_name.items():
        for read in _reads_of(action):
            readers.setdefault(read, set()).add(name)
    case_of: dict[str, str] = {}
    for case, members in router[BUILTIN_KEY]["branches"].items():
        if members == FILTER:
            continue
        stack = list(members)
        while stack:
            current = stack.pop()
            if current in case_of:
                if case_of[current] != case:
                    raise ConfigurationError(
                        f"Route '{router['name']}' in {workflow_file}: '{current}' reads the "
                        f"branch of case '{case_of[current]}' and of case '{case}'. A record "
                        "is in one branch only; gather the branches with '- join:' first.",
                        context={"action_name": current, "route": router["name"]},
                    )
                continue
            case_of[current] = case
            for reader in readers.get(current, ()):
                if reader != router["name"] and not by_name[reader].get(GATHERS_KEY):
                    stack.append(reader)


def _check_cases_against_enum(
    router: dict[str, Any],
    spec: Mapping[str, Any],
    by_name: Mapping[str, dict[str, Any]],
    workflow_file: str,
) -> None:
    action_name, field = spec["field"].split(".", 1)
    where = f"Route '{router['name']}' in {workflow_file}"
    declared = _field_spec(by_name.get(action_name, {}).get("schema"), field)
    kind = declared.get("type") if isinstance(declared, dict) else None
    enum = _field_enum(by_name.get(action_name, {}).get("schema"), field)
    if (kind is not None and kind != "string") or any(
        not isinstance(value, str) for value in enum or []
    ):
        raise ConfigurationError(
            f"{where}: {spec['field']} is not a string field "
            f"({'enum ' + repr(enum) if enum else 'type ' + repr(kind)}). A router matches "
            "string values only, so no record could enter a case.",
            context={"route": router["name"], "field": spec["field"]},
        )
    if enum is None:
        return
    allowed = list(enum)
    for case in spec["cases"]:
        if case not in allowed:
            raise ConfigurationError(
                f"{where}: case '{case}' is not a value of {spec['field']}, whose schema "
                f"allows {', '.join(allowed)}. No record can enter that branch.",
                context={"route": router["name"], "case": case, "enum": allowed},
            )
    uncovered = [value for value in allowed if value not in spec["cases"]]
    if uncovered and not spec["default"]:
        raise ConfigurationError(
            f"{where}: {', '.join(uncovered)} {'is a value' if len(uncovered) == 1 else 'are values'} "
            f"of {spec['field']} with no case, and 'default: {FILTER}' would filter every "
            "such record. Give each a case, or name a default branch.",
            context={"route": router["name"], "uncovered": uncovered},
        )


def _field_spec(schema: Any, field: str) -> Any:
    """The declaration of *field* in a compiled schema, None when it declares none."""
    if not isinstance(schema, dict):
        return None
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        schema = schema["items"]
    fields = schema.get("fields")
    if isinstance(fields, list):
        found = next((f for f in fields if isinstance(f, dict) and f.get("id") == field), None)
        if found is not None:
            return found
    properties = schema.get("properties")
    return properties.get(field) if isinstance(properties, dict) else None


def _field_enum(schema: Any, field: str) -> list[Any] | None:
    """The ``enum`` of *field* in a compiled schema, None when it declares none."""
    if not isinstance(schema, dict):
        return None
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        schema = schema["items"]
    spec: Any = None
    fields = schema.get("fields")
    if isinstance(fields, list):
        spec = next((f for f in fields if isinstance(f, dict) and f.get("id") == field), None)
    properties = schema.get("properties")
    if spec is None and isinstance(properties, dict):
        spec = properties.get(field)
    enum = spec.get("enum") if isinstance(spec, dict) else None
    return enum if isinstance(enum, list) and enum else None


def _branch_members(
    router: dict[str, Any], by_name: Mapping[str, dict[str, Any]]
) -> dict[str, set[str]]:
    """Each case of *router* to the actions of its branch, down to a gathering action."""
    readers: dict[str, list[str]] = {}
    for name, action in by_name.items():
        deps = action.get("dependencies") or []
        for dep in [deps] if isinstance(deps, str) else deps:
            readers.setdefault(dep, []).append(name)
    members: dict[str, set[str]] = {}
    for case, entries in router[BUILTIN_KEY]["branches"].items():
        if not isinstance(entries, list):
            continue
        seen: set[str] = set()
        stack = list(entries)
        while stack:
            name = stack.pop()
            if name in seen or name not in by_name:
                continue
            seen.add(name)
            if not by_name[name].get(GATHERS_KEY):
                stack.extend(readers.get(name, ()))
        members[case] = seen
    return members


def _warn_partial_joins(
    routers: list[dict[str, Any]], by_name: Mapping[str, dict[str, Any]], workflow_file: str
) -> None:
    """Warn of a join that takes some branches of a router but not all of them.

    The records of a branch left out stop at the join, and the run still succeeds.
    """
    joins = [a for a in by_name.values() if (builtin_tool(a) or {}).get("tool") == PICK]
    for router in routers:
        members = _branch_members(router, by_name)
        for join in joins:
            sources = set(join[BUILTIN_KEY]["of"])
            covered = [case for case, names in members.items() if names & sources]
            missing = [case for case in members if case not in covered]
            if covered and missing:
                logger.warning(
                    "Join '%s' in %s takes the branches of router '%s' for %s but not for %s: "
                    "the records of those cases stop at the join.",
                    join["name"],
                    workflow_file,
                    router["name"],
                    ", ".join(covered),
                    ", ".join(missing),
                )


# -- join --------------------------------------------------------------------


def _join(
    entry: dict[str, Any],
    workflow_file: str,
    actions: Mapping[str, dict[str, Any]],
    instances: Mapping[str, Inclusion],
    taken: set[str],
) -> dict[str, Any]:
    name = _entry_name(entry, "join", workflow_file, taken)
    where = f"Join '{name}' in {workflow_file}"
    _refuse_unknown_keys(set(entry), JOIN_KEYS, where)
    raw = entry.get("of")
    if not isinstance(raw, list) or not raw or not all(isinstance(n, str) for n in raw):
        raise ConfigurationError(
            f"{where}: 'of:' must list the last action of each branch it joins.",
            context={"join": name},
        )
    sources: list[str] = []
    for source in raw:
        if source in instances:
            outputs = [instances[source].final(o) for o in instances[source].outputs]
            if len(outputs) != 1:
                raise ConfigurationError(
                    f"{where}: include instance '{source}' declares {len(outputs)} outputs; "
                    "name the action of it to join.",
                    context={"join": name, "instance": source},
                )
            sources.extend(outputs)
        elif source in actions:
            if actions[source].get("versions"):
                raise ConfigurationError(
                    f"{where}: 'of:' names '{source}', which runs as versions, and a record "
                    f"holds only its version outputs. Join the action that merges the versions "
                    f"of '{source}'.",
                    context={"join": name, "source": source},
                )
            sources.append(source)
        else:
            raise ConfigurationError(
                f"{where}: 'of:' names '{source}', which is no action or include instance of "
                "the workflow.",
                context={"join": name, "source": source},
            )
    sources = list(dict.fromkeys(sources))
    return {
        "name": name,
        "kind": "tool",
        "impl": PICK_IMPL,
        "intent": f"Join {', '.join(sources)}",
        "dependencies": sources,
        "context_scope": {"observe": [f"{source}.*" for source in sources]},
        BUILTIN_KEY: {"tool": PICK, "of": sources},
        GATHERS_KEY: True,
    }


def _joined_schema(
    name: str, sources: Sequence[str], by_name: Mapping[str, dict[str, Any]]
) -> dict[str, Any]:
    """Every field of the joined actions' schemas, none required: a record holds one's."""
    fields: dict[str, dict[str, Any]] = {}
    for source in sources:
        schema = by_name.get(source, {}).get("schema")
        if not isinstance(schema, dict):
            continue
        if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
            schema = schema["items"]
        declared: list[dict[str, Any]] = []
        if isinstance(schema.get("fields"), list):
            declared = [f for f in schema["fields"] if isinstance(f, dict) and "id" in f]
        elif isinstance(schema.get("properties"), dict):
            declared = [
                {"id": key, **value}
                for key, value in schema["properties"].items()
                if isinstance(value, dict)
            ]
        for field in declared:
            kept = {k: v for k, v in field.items() if k not in ("expectations", "required")}
            fields.setdefault(str(field["id"]), kept)
    return {
        "name": f"{name}_joined",
        "fields": list(fields.values()),
        "additionalProperties": True,
        "required_by_default": False,
    }


# -- shared ------------------------------------------------------------------


def _entry_name(entry: dict[str, Any], key: str, workflow_file: str, taken: set[str]) -> str:
    name = entry.get(key)
    label = f"'- {key}: {name}' in {workflow_file}"
    if not isinstance(name, str) or not _NAME.match(name):
        raise ConfigurationError(
            f"{label}: the name must start with a letter and hold only letters, digits and '_'.",
            context={key: repr(name)},
        )
    if "__" in name or name.endswith("_") or _VERSION_SUFFIX.search(name):
        raise ConfigurationError(
            f"{label}: the name cannot contain '__', end with '_', or end with '_' and "
            "digits, which reads as a version.",
            context={key: name},
        )
    if name in taken:
        raise ConfigurationError(
            f"{label}: the name '{name}' is already an action of the workflow.",
            context={key: name},
        )
    taken.add(name)
    return name


def _refuse_unknown_keys(keys: set[Any], allowed: Sequence[str], where: str) -> None:
    unknown = sorted(str(key) for key in keys if key not in allowed)
    if unknown:
        raise ConfigurationError(
            f"{where}: unknown key {', '.join(unknown)}. Keys: {', '.join(allowed)}.",
            context={"unknown_keys": unknown},
        )
