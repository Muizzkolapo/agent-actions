"""Shared guard context builder for batch and online paths.

Ensures both prefilter_by_guard (online) and TaskPreparer.prepare (batch)
evaluate guards with identical field_context, closing the "works in batch,
fails online" guard class.

This module is the SINGLE source of truth for guard context construction.
Both paths MUST use build_guard_context — duplicating this logic is a
merge-blocking anti-pattern.
"""

import logging
from functools import lru_cache
from typing import Any

from agent_actions.utils.constants import RUNTIME_BUS_NAMESPACES

logger = logging.getLogger(__name__)


def _guard_can_read_seed(agent_config: dict[str, Any]) -> bool:
    """Whether the action's guard may read `seed`: a SQL clause naming it, or any UDF."""
    if agent_config.get("conditional_clause"):
        return True
    guard = agent_config.get("guard")
    clause = guard.get("clause") if isinstance(guard, dict) else guard
    if not isinstance(clause, str) or "seed" not in clause:
        return False
    return _clause_names_seed(clause)


@lru_cache(maxsize=256)
def _clause_names_seed(clause: str) -> bool:
    from agent_actions.expectations.expression import referenced_field_paths
    from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

    parsed = WhereClauseParser().parse(clause)
    if not parsed.success or parsed.ast is None:
        return False
    return any(path.split(".", 1)[0] == "seed" for path in referenced_field_paths(parsed.ast.root))


def build_guard_context(
    record: dict[str, Any],
    *,
    agent_name: str,
    agent_config: dict[str, Any],
    agent_indices: dict[str, int] | None = None,
    source_data: list[dict[str, Any]] | None = None,
    source_content: Any = None,
    is_first_stage: bool = False,
    version_context: dict[str, Any] | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    dependency_configs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build full field_context for guard evaluation.

    Replicates the context assembly performed by TaskPreparer._load_full_context
    so that both online prefilter and batch prepare evaluate guards against
    identical context structures.

    Args:
        record: The input record; a first-stage record's flat fields are normalized.
        agent_name: Current action name.
        agent_config: Action configuration (contains context_scope, guard, etc.).
        agent_indices: Map of action names to workflow positions (enables dep loading).
        source_content: Pre-resolved source content (batch path provides this
            directly; when given, the record itself is used for non-first-stage).
        is_first_stage: Whether this is the first action in the workflow.
        version_context: Loop iteration metadata (i, idx, length, first, last).
        workflow_metadata: Workflow-level metadata.
        dependency_configs: Per-dependency config (for output_field promotion).

    Returns:
        Full field_context dict with source, dependency, seed, version, and workflow
        namespaces — identical to what TaskPreparer.prepare() provides.
    """
    from agent_actions.processing.source_resolution import (
        resolve_first_stage_source,
        resolve_source_content,
    )
    from agent_actions.prompt.context.scope_builder import build_field_context_with_history
    from agent_actions.prompt.service import PromptPreparationService

    if source_content is not None:
        resolved_source = source_content
    elif is_first_stage:
        resolved_source = resolve_first_stage_source(record)
    else:
        resolved_source = resolve_source_content(
            record,
            record.get("source_guid"),
            source_data,
            action_name=agent_name,
        )

    field_context = build_field_context_with_history(
        agent_name=agent_name,
        agent_config=agent_config,
        agent_indices=agent_indices,
        source_content=resolved_source,
        version_context=version_context,
        workflow_metadata=workflow_metadata,
        current_item=record,
        context_scope=agent_config.get("context_scope"),
    )
    field_context.pop("_dependency_metadata", None)

    # The declared seed, loaded through the prompt's loader, for a guard that can read it.
    # Every declared key, as a guard reads the record whole: `context_scope` decides what
    # the action is handed, not what its guard sees. Shared and read-only (the evaluator
    # only reads, and hands a UDF a read-only view), so each file is parsed once.
    if _guard_can_read_seed(agent_config):
        seed = PromptPreparationService.load_seed_data(
            agent_config,
            agent_config.get("context_scope") or {},
            agent_name,
            source=field_context.get("source"),
            shared=True,
        )
        if seed:
            field_context["seed"] = seed

    # Promote output_field values to top-level so guards can reference them
    # directly (e.g., "severity" instead of "assess.severity").
    if dependency_configs:
        for dep_name, dep_config in dependency_configs.items():
            if not dep_config or "output_field" not in dep_config:
                continue
            of_name = dep_config["output_field"]
            dep_data = field_context.get(dep_name)
            # Unwrap single-item list (common storage shape for output_field actions)
            if isinstance(dep_data, list) and len(dep_data) == 1:
                dep_data = dep_data[0]
            if isinstance(dep_data, dict) and of_name in dep_data:
                if of_name in RUNTIME_BUS_NAMESPACES:
                    # A promotion may not take a framework namespace's name. The evaluator
                    # reads these keys as the framework's own answer, so a promoted field
                    # sitting under one would be preferred over the record's.
                    logger.warning(
                        "output_field '%s' from action '%s' is a framework namespace name "
                        "and is not promoted — use '%s.%s' in guard conditions instead",
                        of_name,
                        dep_name,
                        dep_name,
                        of_name,
                    )
                elif of_name not in field_context:
                    field_context[of_name] = dep_data[of_name]
                else:
                    logger.warning(
                        "output_field '%s' from action '%s' collides with existing "
                        "field in context — use '%s.%s' in guard conditions instead",
                        of_name,
                        dep_name,
                        dep_name,
                        of_name,
                    )

    return field_context
