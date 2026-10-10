"""Preflight checks that what an action depends on and what it reads agree."""

from __future__ import annotations

import logging
from typing import Any

from agent_actions.expectations.expression import referenced_field_paths
from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser
from agent_actions.prompt.context.scope_inference import (
    expand_version_base_names,
    infer_dependencies,
)
from agent_actions.prompt.context.scope_parsing import parse_field_reference

logger = logging.getLogger(__name__)


def _referenced_namespaces(context_scope: dict[str, Any], action_name: str) -> set[str]:
    """Namespaces named by well-formed observe/passthrough refs.

    Malformed refs are skipped, exactly as the runtime skips them — a
    dotless ref like ``"producer"`` must not satisfy a dependency here
    when it would not satisfy it at execution time.

    Deliberately not ``scope_parsing.extract_action_names_from_context_scope``:
    that fires a ``ContextFieldSkippedEvent`` per malformed ref, and the
    preceding ``infer_dependencies`` call already fires those for the same
    refs — reusing it would surface duplicate skip events during inspect.
    """
    refs = list(context_scope.get("observe") or []) + list(context_scope.get("passthrough") or [])
    namespaces: set[str] = set()
    for ref in refs:
        try:
            namespace, _ = parse_field_reference(ref)
        except ValueError as exc:
            logger.debug(
                "Skipping unparseable context_scope ref %r on '%s': %s", ref, action_name, exc
            )
            continue
        namespaces.add(namespace)
    return namespaces


def find_missing_observe_deps(action_configs: dict[str, dict[str, Any]]) -> list[str]:
    """Return one finding per declared dependency with no field in context_scope.

    Pure preflight mirror of the fatal runtime check in
    ``scope_namespace._extract_allowed_fields_per_dependency``: no events,
    no raising on the first offender — all offenders are reported.

    The dependency set comes from ``infer_dependencies`` exactly as the
    runtime's scope_builder derives it. That is load-bearing: the loader
    expands a versioned producer into ``<base>_N`` actions and rewrites the
    consumer's observe refs to the branch names while its ``dependencies``
    keep the base name — comparing raw config strings would reject those
    valid workflows.
    """
    findings: list[str] = []
    workflow_actions = list(action_configs)
    for name, cfg in action_configs.items():
        input_sources, context_sources = infer_dependencies(
            cfg, workflow_actions, name, validate=False
        )
        deps = input_sources + context_sources
        if not deps:
            continue
        scope = cfg.get("context_scope") or {}
        if not scope:
            findings.append(
                f"{name}: has dependencies {deps} but no context_scope. "
                f"Every dependency needs at least one field declaration."
            )
            continue
        referenced = _referenced_namespaces(scope, name)
        for dep in deps:
            if dep not in referenced:
                findings.append(
                    f"{name}: dependency '{dep}' declared but not referenced in "
                    f"context_scope. Add '{dep}.*' or '{dep}.<field>' to observe "
                    f"or passthrough, or drop '{dep}' from dependencies."
                )
    return findings


def _upstream_through_dependencies(
    action_configs: dict[str, dict[str, Any]],
) -> dict[str, set[str]]:
    """Each action's ancestors through ``dependencies``, a version base meaning every branch."""
    workflow_actions = list(action_configs)
    direct: dict[str, list[str]] = {}
    for name, cfg in action_configs.items():
        declared = cfg.get("dependencies") or []
        if isinstance(declared, str):
            declared = [declared]
        named = [dep for dep in declared if isinstance(dep, str)]
        direct[name] = expand_version_base_names(named, workflow_actions)
    upstream: dict[str, set[str]] = {}
    for name in action_configs:
        reached: set[str] = set()
        pending = list(direct[name])
        while pending:
            dep = pending.pop()
            if dep not in reached:
                reached.add(dep)
                pending.extend(direct.get(dep, ()))
        upstream[name] = reached
    return upstream


def _guard_namespaces(cfg: dict[str, Any], parser: WhereClauseParser) -> list[str]:
    """Namespaces a guard clause names; a clause that does not parse is left to the guard check."""
    guard = cfg.get("guard")
    clause = guard.get("clause") if isinstance(guard, dict) else None
    if not isinstance(clause, str) or not clause:
        return []
    parsed = parser.parse_cached(clause)
    if not parsed.success or parsed.ast is None:
        return []
    paths = referenced_field_paths(parsed.ast.root)
    return list(dict.fromkeys(path.split(".", 1)[0] for path in paths if "." in path))


def find_reads_not_upstream(action_configs: dict[str, dict[str, Any]]) -> list[str]:
    """Return one finding per action an action names that is not upstream of it.

    A name in the context scope or prompt is what the run order counts
    (``infer_dependencies``); a guard reads its names off the same record. A
    record carries the namespaces of the actions upstream of it through
    ``dependencies`` and no other, and the reader is not reset when another action
    it names fails and runs again. A version merge whose every branch is missing is
    reported by its base, the name ``dependencies`` takes.
    """
    findings: list[str] = []
    workflow_actions = list(action_configs)
    operational = {name for name, cfg in action_configs.items() if cfg.get("is_operational", True)}
    upstream = _upstream_through_dependencies(action_configs)
    parser = WhereClauseParser()
    branches: dict[str, set[str]] = {}
    for name in workflow_actions:
        base = action_configs[name].get("version_base_name")
        if name in operational and isinstance(base, str) and base not in action_configs:
            branches.setdefault(base, set()).add(name)
    for name in workflow_actions:
        if name not in operational:
            continue
        input_sources, context_sources = infer_dependencies(
            action_configs[name], workflow_actions, name, validate=False
        )
        where: dict[str, str] = {}
        for read in input_sources + context_sources:
            where.setdefault(read, "context_scope or prompt")
        for read in _guard_namespaces(action_configs[name], parser):
            where.setdefault(read, "guard")
        missing = {
            read: place
            for read, place in where.items()
            if read != name and read in operational and read not in upstream[name]
        }
        for base, members in branches.items():
            if members <= missing.keys():
                place = missing[min(members)]
                for member in members:
                    del missing[member]
                missing[base] = place
        for read, place in missing.items():
            findings.append(
                f"{name}: names '{read}' in its {place}, but '{read}' is "
                f"not upstream of it through its dependencies, so '{read}' is not sure to "
                f"be on the records it reads, and '{name}' is not run again when '{read}' "
                f"fails and runs again. Add '{read}' to its dependencies, or depend on an "
                f"action downstream of '{read}'."
            )
    return findings
