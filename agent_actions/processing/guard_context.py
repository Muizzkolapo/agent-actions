"""Shared guard context builder for batch and online paths.

Ensures both prefilter_by_guard (online) and TaskPreparer.prepare (batch)
evaluate guards with identical field_context, closing the "works in batch,
fails online" guard class.

This module is the SINGLE source of truth for guard context construction.
Both paths MUST use build_guard_context — duplicating this logic is a
merge-blocking anti-pattern.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


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
        record: The input record (must have "content" dict).
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
        Full field_context dict with source, dependency, version, and workflow
        namespaces — identical to what TaskPreparer.prepare() provides.
    """
    from agent_actions.prompt.context.scope_builder import build_field_context_with_history
    from agent_actions.utils.content import get_existing_content

    content = get_existing_content(record)

    if source_content is not None:
        resolved_source = source_content
    elif is_first_stage:
        resolved_source = content
    else:
        record_content = record.get("content", {})
        if isinstance(record_content, dict) and "source" in record_content:
            resolved_source = record
        elif source_data and record.get("source_guid"):
            from agent_actions.input.preprocessing.transformation.transformer import (
                DataTransformer,
            )

            resolved_source = DataTransformer.get_content_by_source_guid(
                source_data, record["source_guid"]
            )
            if resolved_source is None:
                resolved_source = record
        else:
            resolved_source = record

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
                if of_name not in field_context:
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
