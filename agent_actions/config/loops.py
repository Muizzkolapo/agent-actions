"""Unroll the loop entries of a workflow into include instances, one per iteration.

``- loop: <name>`` with ``include: <branch>`` and ``max_iterations: N`` becomes N
instances ``<name>_iter<k>`` of the branch. From iteration 2, the actions that start
the branch take their records from the previous iteration's ``result`` action and send
a record for which ``until`` held there elsewhere; ``feedback`` inputs are bound to the
previous iteration, and to none in iteration 1. A built-in ``pick`` action named after
the loop gathers every record back and writes the ``result`` of the last iteration
that ran for it.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from jinja2 import TemplateSyntaxError

from agent_actions.errors import ConfigurationError
from agent_actions.input.context.normalizer import DIRECTIVE_REGISTRY
from agent_actions.llm.providers.tools.builtin import BUILTIN_KEY, PICK, builtin_tool
from agent_actions.record.elsewhere import GATHERS_KEY, SENDS_ELSEWHERE_KEY

LOOP_KEYS = ("loop", "include", "max_iterations", "inputs", "feedback", "until", "result")
LOOP_ORIGIN_KEY = "_loop"
MAX_ITERATIONS = 10
ITERATION_SEPARATOR = "_iter"
PICK_IMPL = "agac.pick"
# What a feedback input is bound to in iteration 1: a Jinja none in the alias header.
NO_FEEDBACK = "none"


def is_loop(entry: Any) -> bool:
    return isinstance(entry, dict) and "loop" in entry and "name" not in entry


def instance_name(loop: str, iteration: int) -> str:
    """The include instance of *loop*'s *iteration*; it cannot end in ``_<digits>``."""
    return f"{loop}{ITERATION_SEPARATOR}{iteration}"


def loop_of(config: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The loop settings an iteration action or a loop's pick action carries."""
    if not isinstance(config, Mapping):
        return None
    origin = config.get("_include")
    if isinstance(origin, Mapping) and isinstance(origin.get("loop"), dict):
        return dict(origin["loop"])
    spec = builtin_tool(config)
    if spec is not None and isinstance(spec.get("loop"), dict):
        return dict(spec["loop"])
    return None


def is_loop_pick(config: Mapping[str, Any] | None) -> bool:
    spec = builtin_tool(config)
    return spec is not None and spec["tool"] == PICK and isinstance(spec.get("loop"), dict)


def unroll_loops(
    data: dict[str, Any],
    workflow_file: str,
    branches: Mapping[str, Any],
    available: Sequence[str],
) -> dict[str, Any]:
    """*data* with each loop entry replaced by its include entries and its pick action."""
    from agent_actions.config.routes import entry_name

    entries: list[Any] = data["actions"]
    for entry in entries:
        if isinstance(entry, dict) and "include" in entry and LOOP_ORIGIN_KEY in entry:
            raise ConfigurationError(
                f"Include '{entry.get('include')}' in {workflow_file}: '{LOOP_ORIGIN_KEY}' is "
                "set by the load for a loop and cannot be written in a workflow.",
            )
    if not any(is_loop(entry) for entry in entries):
        return data
    taken = {e["name"] for e in entries if isinstance(e, dict) and isinstance(e.get("name"), str)}
    expanded: list[Any] = []
    for entry in entries:
        if not is_loop(entry):
            expanded.append(entry)
            continue
        name = entry_name(entry, "loop", workflow_file, taken)
        expanded.extend(_unrolled(entry, name, workflow_file, branches, available))
    return {**data, "actions": expanded}


def _unrolled(
    entry: dict[str, Any],
    name: str,
    workflow_file: str,
    branches: Mapping[str, Any],
    available: Sequence[str],
) -> list[dict[str, Any]]:
    from agent_actions.config.includes import parse_branch

    where = f"Loop '{name}' in {workflow_file}"
    unknown = sorted(str(key) for key in entry if key not in LOOP_KEYS)
    if unknown:
        raise ConfigurationError(
            f"{where}: unknown key {', '.join(unknown)}. Keys: {', '.join(LOOP_KEYS)}.",
            context={"loop": name, "unknown_keys": unknown},
        )
    for key in ("include", "max_iterations", "until", "result"):
        if key not in entry:
            raise ConfigurationError(f"{where}: '{key}:' is required.", context={"loop": name})
    branch_name = entry["include"]
    if not isinstance(branch_name, str) or branch_name not in branches:
        found = ", ".join(available) if available else "none"
        raise ConfigurationError(
            f"{where}: 'include: {branch_name}' names no branch file. Branch files found: "
            f"{found}.",
            context={"loop": name, "branch": repr(branch_name)},
        )
    branch = parse_branch(branch_name, branches[branch_name], workflow_file)
    count = entry["max_iterations"]
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_ITERATIONS:
        raise ConfigurationError(
            f"{where}: 'max_iterations:' must be a whole number from 1 to {MAX_ITERATIONS}, "
            f"got {count!r}.",
            context={"loop": name},
        )
    inputs = _string_map(entry.get("inputs"), "inputs", "each branch input to an action", where)
    feedback = _string_map(
        entry.get("feedback"), "feedback", "each branch input to a branch action", where
    )
    actions = {action["name"]: action for action in branch.actions}
    result = _branch_action(entry["result"], "result", actions, branch.label, where)
    if result not in branch.outputs:
        raise ConfigurationError(
            f"{where}: 'result: {result}' is not listed under 'outputs:' of {branch.label}. "
            "The loop's result is read outside the branch; list it there.",
            context={"loop": name, "result": result},
        )
    if actions[result].get("versions"):
        raise ConfigurationError(
            f"{where}: 'result: {result}' has versions. Name one action as the result.",
            context={"loop": name, "result": result},
        )
    for key, source in feedback.items():
        if key not in branch.inputs:
            raise ConfigurationError(
                f"{where}: 'feedback:' names '{key}', which {branch.label} does not declare "
                f"under 'inputs:'. Branch inputs: {', '.join(branch.inputs) or 'none'}.",
                context={"loop": name, "input": key},
            )
        if key in inputs:
            raise ConfigurationError(
                f"{where}: '{key}' is under both 'inputs:' and 'feedback:'. A feedback input "
                "is bound by the loop.",
                context={"loop": name, "input": key},
            )
        _branch_action(source, f"feedback: {key}", actions, branch.label, where)
        if source not in branch.outputs:
            raise ConfigurationError(
                f"{where}: 'feedback: {{{key}: {source}}}': '{source}' is not listed under "
                f"'outputs:' of {branch.label}. An iteration reads it from the one before; "
                "list it there.",
                context={"loop": name, "input": key},
            )
    until = _checked_until(entry["until"], actions, result, branch.label, where)
    _refuse_feedback_in_guards(branch.actions, feedback, where)
    entries = _entry_names(branch.actions)
    for action in branch.actions:
        has_guard = action.get("guard") is not None or action.get("conditional_clause")
        if action["name"] in entries and has_guard:
            raise ConfigurationError(
                f"{where}: '{action['name']}', which starts {branch.label}, has a guard of its "
                "own. The loop gives it the guard that ends the loop for a record; move the "
                "condition to the next action of the branch.",
                context={"loop": name, "action_name": action["name"]},
            )
    settings = {
        "name": name,
        "branch": branch_name,
        "max_iterations": count,
        "until": until,
        "result": result,
        "feedback": sorted(feedback),
    }
    includes: list[dict[str, Any]] = []
    for k in range(1, count + 1):
        bindings = dict(inputs)
        for key, source in feedback.items():
            bindings[key] = name if k == 1 else f"{instance_name(name, k - 1)}__{source}"
        includes.append(
            {
                "include": branch_name,
                "as": instance_name(name, k),
                "inputs": bindings,
                LOOP_ORIGIN_KEY: {**settings, "iteration": k},
            }
        )
    results = [f"{instance_name(name, k)}__{result}" for k in range(count, 0, -1)]
    pick = {
        "name": name,
        "kind": "tool",
        "impl": PICK_IMPL,
        "intent": f"Take the {result} of the last iteration of loop {name}",
        "dependencies": results,
        "context_scope": {"observe": [f"{source}.*" for source in results]},
        BUILTIN_KEY: {"tool": PICK, "of": results, "loop": settings},
        GATHERS_KEY: True,
    }
    return [*includes, pick]


def _string_map(value: Any, key: str, what: str, where: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise ConfigurationError(f"{where}: '{key}:' must map {what}.")
    return dict(value)


def _branch_action(
    value: Any, key: str, actions: Mapping[str, Any], label: str, where: str
) -> str:
    if not isinstance(value, str) or value not in actions:
        raise ConfigurationError(
            f"{where}: '{key}: {value}' names no action of {label}. Branch actions: "
            f"{', '.join(actions)}.",
            context={"key": key},
        )
    return value


def _dependencies(action: Mapping[str, Any]) -> list[str]:
    dependencies = action.get("dependencies") or []
    if isinstance(dependencies, str):
        dependencies = [dependencies]
    return [d for d in dependencies if isinstance(d, str)]


def _entry_names(actions: Sequence[Mapping[str, Any]]) -> set[str]:
    """The branch actions that depend on no other action of the branch."""
    names = {action["name"] for action in actions}
    return {a["name"] for a in actions if not names.intersection(_dependencies(a))}


def _upstream(name: str, actions: Mapping[str, Mapping[str, Any]]) -> set[str]:
    """*name* and every branch action it depends on, however deep."""
    seen: set[str] = set()
    stack = [name]
    while stack:
        current = stack.pop()
        if current in seen or current not in actions:
            continue
        seen.add(current)
        stack.extend(_dependencies(actions[current]))
    return seen


def clause_paths(clause: str) -> list[str]:
    """Each field path a guard clause reads; raises ValueError when it does not parse."""
    from agent_actions.expectations.expression import referenced_field_paths
    from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

    parsed = WhereClauseParser().parse(clause)
    if not parsed.success or parsed.ast is None:
        raise ValueError(parsed.error.message if parsed.error else "it does not parse")
    return referenced_field_paths(parsed.ast.root)


def _checked_until(
    until: Any, actions: Mapping[str, Mapping[str, Any]], result: str, label: str, where: str
) -> str:
    if not isinstance(until, str) or not until.strip():
        raise ConfigurationError(f"{where}: 'until:' must be a guard condition.")
    if until.strip().lower().startswith("udf:"):
        raise ConfigurationError(
            f"{where}: 'until: {until}' is a UDF guard. Write a condition on the fields of "
            "the branch actions.",
        )
    try:
        paths = clause_paths(until)
    except ValueError as e:
        raise ConfigurationError(
            f"{where}: 'until: {until}' is not a valid condition: {e}"
        ) from None
    upstream = _upstream(result, actions)
    for path in paths:
        root = path.split(".", 1)[0]
        if "." not in path or root not in upstream:
            raise ConfigurationError(
                f"{where}: 'until: {until}' reads '{path}'. It may read only fields of the "
                f"actions of {label} that run up to '{result}', as <action>.<field>: "
                f"{', '.join(sorted(upstream))}.",
                context={"until": until, "field": path},
            )
    if not paths:
        raise ConfigurationError(
            f"{where}: 'until: {until}' reads no field of the branch. It must read the "
            "verdict of an iteration.",
            context={"until": until},
        )
    return until


def _refuse_feedback_in_guards(
    actions: Sequence[Mapping[str, Any]], feedback: Mapping[str, str], where: str
) -> None:
    """Refuse a guard or version source that reads a feedback input: iteration 1 has none."""
    from agent_actions.config.includes import renamed_clause

    marker = "\x00feedback"
    names = {key: marker for key in feedback}
    for action in actions:
        guard = action.get("guard")
        clause = guard.get("condition") if isinstance(guard, dict) else guard
        if isinstance(clause, str) and marker in renamed_clause(clause, names):
            raise ConfigurationError(
                f"{where}: the guard of '{action['name']}' reads a feedback input. Iteration "
                "1 has no feedback, so the guard could not be evaluated there; read it in the "
                "prompt or the tool instead.",
                context={"action_name": action["name"]},
            )
        consumption = action.get("version_consumption")
        if isinstance(consumption, dict) and consumption.get("source") in feedback:
            raise ConfigurationError(
                f"{where}: '{action['name']}' consumes the versions of a feedback input, "
                "which iteration 1 does not have.",
                context={"action_name": action["name"]},
            )


def expand_loops(data: Any) -> Any:
    """Wire the iterations of each loop of *data*, whose includes are expanded.

    In iteration 1 a feedback input is bound to none. From iteration 2 the actions that
    start the branch depend on the previous iteration's result only, and their guard
    sends a record for which ``until`` held there elsewhere.
    """
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list):
        return data
    iterations = [a for a in actions if isinstance(a, dict) and loop_of(a) and "_include" in a]
    if not iterations:
        return data
    data = copy.deepcopy(data)
    by_instance: dict[str, list[dict[str, Any]]] = {}
    for action in data["actions"]:
        if isinstance(action, dict) and "_include" in action and loop_of(action):
            by_instance.setdefault(action["_include"]["instance"], []).append(action)
    for members in by_instance.values():
        settings = loop_of(members[0])
        assert settings is not None
        if settings["iteration"] == 1:
            _without_feedback(members, settings)
        else:
            _entered_from_previous(members, settings)
    return data


def _without_feedback(members: list[dict[str, Any]], settings: Mapping[str, Any]) -> None:
    placeholder = settings["name"]
    for action in members:
        names = action["_include"]["names"]
        for key in settings["feedback"]:
            names[key] = NO_FEEDBACK
        dependencies = action.get("dependencies")
        if isinstance(dependencies, list):
            action["dependencies"] = [d for d in dependencies if d != placeholder]
        elif dependencies == placeholder:
            action.pop("dependencies")
        scope = action.get("context_scope")
        if isinstance(scope, dict):
            for directive, refs in list(scope.items()):
                if DIRECTIVE_REGISTRY.get(directive, {}).get("type") == "list" and isinstance(
                    refs, list
                ):
                    scope[directive] = [r for r in refs if not _rooted_at(r, placeholder)]


def _rooted_at(ref: Any, name: str) -> bool:
    return isinstance(ref, str) and ref.split(".", 1)[0].rstrip("?") == name


def _entered_from_previous(members: list[dict[str, Any]], settings: Mapping[str, Any]) -> None:
    from agent_actions.config.includes import renamed_clause

    previous = instance_name(settings["name"], settings["iteration"] - 1)
    local_names = {action["_include"]["local_name"] for action in members}
    previous_names = {local: f"{previous}__{local}" for local in local_names}
    condition = renamed_clause(settings["until"], previous_names)
    finals = {action["name"] for action in members}
    for action in members:
        if finals.intersection(_dependencies(action)):
            continue
        action["dependencies"] = [previous_names[settings["result"]]]
        action["guard"] = {
            "condition": f"NOT ({condition})",
            "on_false": "filter",
            "passthrough_on_error": False,
        }
        action[SENDS_ELSEWHERE_KEY] = True


def finish_loops(data: Any, workflow_file: str, project_root: Path | None = None) -> None:
    """Check each loop against the compiled workflow, and give its pick the result's schema.

    Runs once the schemas are compiled into the actions.
    """
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list):
        return
    by_name = {
        a["name"]: a for a in actions if isinstance(a, dict) and isinstance(a.get("name"), str)
    }
    picks = [a for a in by_name.values() if is_loop_pick(a)]
    if not picks:
        return
    members = {
        name for name, action in by_name.items() if loop_of(action) and "_include" in action
    }
    for pick in picks:
        settings = loop_of(pick)
        assert settings is not None
        where = f"Loop '{pick['name']}' in {workflow_file}"
        first = instance_name(pick["name"], 1)
        for path in clause_paths(settings["until"]):
            local, field = path.split(".", 1)
            schema = by_name.get(f"{first}__{local}", {}).get("schema")
            declared = _declared_fields(schema)
            if declared is not None and field.split(".", 1)[0] not in declared:
                raise ConfigurationError(
                    f"{where}: 'until: {settings['until']}' reads '{path}', but the schema of "
                    f"'{local}' has no field '{field.split('.', 1)[0]}'. Its fields: "
                    f"{', '.join(declared) or 'none'}.",
                    context={"loop": pick["name"], "field": path},
                )
        last = instance_name(pick["name"], settings["max_iterations"])
        schema = by_name.get(f"{last}__{settings['result']}", {}).get("schema")
        if isinstance(schema, dict) and not pick.get("schema"):
            pick["schema"] = {**_without_rules(schema), "name": f"{pick['name']}_result"}
    _refuse_file_granularity(data, members, workflow_file, project_root)
    _refuse_outside_reads(by_name, members, workflow_file)


def _without_rules(schema: dict[str, Any]) -> dict[str, Any]:
    """A copy of *schema* with no ``expectations``, of the schema or of a field.

    Its rules read the names of the last iteration, which a record that left the loop
    early does not hold; the join drops them for the same reason.
    """
    copied = copy.deepcopy(schema)
    shape = copied.get("items") if copied.get("type") == "array" else copied
    fields = shape.get("fields") if isinstance(shape, dict) else None
    properties = shape.get("properties") if isinstance(shape, dict) else None
    for owner in [
        copied,
        shape,
        *(fields if isinstance(fields, list) else []),
        *(properties.values() if isinstance(properties, dict) else []),
    ]:
        if isinstance(owner, dict):
            owner.pop("expectations", None)
    return copied


def _declared_fields(schema: Any) -> list[str] | None:
    """The top-level field names of a compiled schema; None when it declares none."""
    if not isinstance(schema, dict):
        return None
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        schema = schema["items"]
    if isinstance(schema.get("fields"), list):
        return [str(f["id"]) for f in schema["fields"] if isinstance(f, dict) and "id" in f]
    if isinstance(schema.get("properties"), dict):
        return [str(key) for key in schema["properties"]]
    return None


def _refuse_file_granularity(
    data: dict[str, Any], members: set[str], workflow_file: str, project_root: Path | None
) -> None:
    from agent_actions.config.includes import inherited_granularities
    from agent_actions.output.response.expander_validation import is_file_granularity

    granularities = inherited_granularities(data, project_root)
    for action in data["actions"]:
        if not isinstance(action, dict) or action.get("name") not in members:
            continue
        granularity = granularities.get(action["name"])
        if granularity is not None and is_file_granularity(granularity):
            settings = loop_of(action) or {}
            local = action["_include"]["local_name"]
            raise ConfigurationError(
                f"Loop '{settings.get('name')}' in {workflow_file}: '{local}' of branch "
                f"'{settings.get('branch')}' runs at File granularity. A loop runs each "
                "record on its own; every action of its branch must run per record.",
                context={"loop": settings.get("name"), "action_name": local},
            )


def _refuse_outside_reads(
    by_name: Mapping[str, dict[str, Any]], members: set[str], workflow_file: str
) -> None:
    """Refuse an action outside a loop that reads one of its iterations, not the loop."""
    from agent_actions.validation.static_analyzer.reference_extractor import ReferenceExtractor

    extractor = ReferenceExtractor()
    for name, action in by_name.items():
        if name in members or is_loop_pick(action):
            continue
        reads = set(_dependencies(action))
        scope = action.get("context_scope")
        if isinstance(scope, dict):
            for directive, refs in scope.items():
                if DIRECTIVE_REGISTRY.get(directive, {}).get("type") == "list" and isinstance(
                    refs, list
                ):
                    reads.update(
                        r.split(".", 1)[0].rstrip("?") for r in refs if isinstance(r, str)
                    )
        guard = action.get("guard")
        clause = guard.get("condition") if isinstance(guard, dict) else guard
        if isinstance(clause, str) and not clause.strip().lower().startswith("udf:"):
            try:
                reads.update(path.split(".", 1)[0] for path in clause_paths(clause))
            except ValueError:
                pass  # a guard that does not parse is refused by the guard check
        try:
            reads.update(r.source_agent for r in extractor.extract_from_agent(action))
        except TemplateSyntaxError:
            pass  # a prompt that does not parse is refused by the prompt check
        for read in sorted(reads & members):
            settings = loop_of(by_name[read]) or {}
            raise ConfigurationError(
                f"Action '{name}' in {workflow_file} reads '{read}', an action of iteration "
                f"{settings.get('iteration')} of loop '{settings.get('name')}'. Outside the "
                f"loop, read '{settings.get('name')}': it holds the "
                f"{settings.get('result')} of the last iteration that ran for each record.",
                context={"action_name": name, "loop": settings.get("name")},
            )
