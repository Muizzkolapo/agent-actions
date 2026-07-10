"""Preflight check: every declared dependency needs an observe/passthrough field."""

from __future__ import annotations

import logging
from typing import Any

from agent_actions.prompt.context.scope_parsing import parse_field_reference

logger = logging.getLogger(__name__)


def _referenced_namespaces(context_scope: dict[str, Any], action_name: str) -> set[str]:
    """Namespaces named by well-formed observe/passthrough refs.

    Malformed refs are skipped, exactly as the runtime skips them — a
    dotless ref like ``"producer"`` must not satisfy a dependency here
    when it would not satisfy it at execution time.
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
    """
    findings: list[str] = []
    for name, cfg in action_configs.items():
        deps = cfg.get("dependencies") or []
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
