"""Prune ``context_scope.drop`` entries targeting unreachable namespaces.

Shared by the coordinator and ``WorkflowInspector`` so post-prune
state matches across both paths."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _get_reachable_actions(action_name: str, action_configs: dict[str, dict[str, Any]]) -> set[str]:
    reachable: set[str] = set()
    stack = list(action_configs.get(action_name, {}).get("depends_on") or [])

    while stack:
        dep = stack.pop()
        if dep in reachable:
            continue
        reachable.add(dep)
        dep_config = action_configs.get(dep, {})
        for upstream in dep_config.get("depends_on") or []:
            if upstream not in reachable:
                stack.append(upstream)

    return reachable


def strip_unreachable_drops(action_configs: dict[str, dict[str, Any]]) -> None:
    """Strip drops on namespaces outside an action's dep chain — they're
    no-ops at runtime but produce per-record warnings."""
    all_action_names = set(action_configs.keys())

    for action_name, config in action_configs.items():
        context_scope = config.get("context_scope")
        if not context_scope or not isinstance(context_scope, dict):
            continue

        drop_refs = context_scope.get("drop")
        if not isinstance(drop_refs, list) or not drop_refs:
            continue

        reachable = _get_reachable_actions(action_name, action_configs)

        filtered: list[str] = []
        for ref in drop_refs:
            if not isinstance(ref, str) or "." not in ref:
                filtered.append(ref)
                continue

            ns_name = ref.split(".", 1)[0]

            # Special namespaces, loop, and reachable actions stay.
            if ns_name not in all_action_names or ns_name in reachable:
                filtered.append(ref)
                continue

            logger.debug(
                "Stripped unreachable drop '%s' from action '%s'",
                ref,
                action_name,
            )

        if len(filtered) != len(drop_refs):
            context_scope["drop"] = filtered


__all__ = ["strip_unreachable_drops"]
