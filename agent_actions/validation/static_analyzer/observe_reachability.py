"""Preflight check: observe field reachability from declared dependencies.

Catches the case where an action observes a field from an action that runs
AFTER its declared dependency — meaning the record snapshot won't carry that
field at runtime. Hard error at config time, not a runtime surprise.
"""

from __future__ import annotations

from typing import Any

# Namespaces that are not actions (injected from external sources)
_SPECIAL_NAMESPACES = frozenset({"seed", "source", "staging", "version"})


def check_observe_reachability(actions: dict[str, dict[str, Any]]) -> list[str]:
    """Check that all observe fields reference actions reachable from dependencies.

    Args:
        actions: Dict mapping action_name → action config dict. Each config
            has 'dependencies' (list[str]) and optionally
            'context_scope.observe' (list[str] of 'namespace.field' refs).

    Returns:
        List of error messages. Empty list = all observe fields are reachable.
    """
    # Build the DAG: action → set of transitive ancestors
    ancestors = _build_ancestor_map(actions)
    errors: list[str] = []

    for action_name, config in actions.items():
        observe = config.get("context_scope", {}).get("observe", [])
        if not observe:
            continue

        deps = config.get("dependencies", [])
        if not deps:
            continue

        # All actions transitively reachable from ANY declared dependency
        reachable = set()
        for dep in deps:
            reachable.add(dep)
            reachable.update(ancestors.get(dep, set()))

        # Check each observed namespace
        for field_ref in observe:
            ns_name = field_ref.split(".")[0]

            if ns_name in _SPECIAL_NAMESPACES:
                continue
            if ns_name not in actions:
                continue  # Unknown namespace — other validators handle this
            if ns_name == action_name:
                continue  # Self-reference
            if ns_name in reachable:
                continue  # Reachable — the record will have this field

            # Unreachable: observed action is NOT transitively before any dependency
            latest_dep = _find_latest_dep(deps, ancestors)
            errors.append(
                f"Action '{action_name}' observes '{field_ref}' but "
                f"'{ns_name}' is not transitively before dependency "
                f"'{latest_dep}' in the DAG. The record from your dependency "
                f"won't carry this field. Fix: add '{ns_name}' to dependencies "
                f"or use a later dependency that runs after '{ns_name}'."
            )

    return errors


def _build_ancestor_map(actions: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    """Build transitive ancestor sets for each action."""
    ancestors: dict[str, set[str]] = {name: set() for name in actions}

    # BFS/DFS per node to find all ancestors
    for action_name in actions:
        visited: set[str] = set()
        stack = list(actions[action_name].get("dependencies", []))
        while stack:
            dep = stack.pop()
            if dep in visited or dep not in actions:
                continue
            visited.add(dep)
            stack.extend(actions[dep].get("dependencies", []))
        ancestors[action_name] = visited

    return ancestors


def _find_latest_dep(deps: list[str], ancestors: dict[str, set[str]]) -> str:
    """Find the dependency that is latest (deepest) in the DAG.

    Simple heuristic: the dep with the most ancestors is latest.
    """
    if len(deps) == 1:
        return deps[0]

    return max(deps, key=lambda d: len(ancestors.get(d, set())))
