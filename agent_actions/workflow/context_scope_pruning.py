"""Prune ``context_scope.drop`` entries targeting unreachable namespaces.

Shared by the coordinator and ``WorkflowInspector`` so post-prune
state matches across both paths."""

from __future__ import annotations

import logging
from typing import Any

from agent_actions.validation.dep_observe_validator import upstream_through_dependencies

logger = logging.getLogger(__name__)


def strip_unreachable_drops(action_configs: dict[str, dict[str, Any]]) -> None:
    """Strip drops on namespaces outside an action's dep chain — they're
    no-ops at runtime but produce per-record warnings.

    The chain is pre-flight's, a version base in ``dependencies`` meaning every
    branch, so a drop on a version merge naming a branch or an action above the
    branches is kept.
    """
    all_action_names = set(action_configs.keys())
    upstream = upstream_through_dependencies(action_configs)

    for action_name, config in action_configs.items():
        context_scope = config.get("context_scope")
        if not context_scope or not isinstance(context_scope, dict):
            continue

        drop_refs = context_scope.get("drop")
        if not isinstance(drop_refs, list) or not drop_refs:
            continue

        reachable = upstream[action_name]

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
