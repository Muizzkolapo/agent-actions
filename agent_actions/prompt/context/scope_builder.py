"""Field context builder — reads from record's namespaced content."""

import logging
from typing import Any

from agent_actions.errors import ConfigurationError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.io_events import ContextNamespaceLoadedEvent
from agent_actions.prompt.context.scope_inference import infer_dependencies
from agent_actions.prompt.context.scope_namespace import (
    _extract_allowed_fields_per_dependency,
    _extract_content_data,
    _filter_and_store_fields,
)

logger = logging.getLogger(__name__)

__all__ = [
    "build_field_context_with_history",
]


def build_field_context_with_history(
    agent_name: str,
    agent_config: dict | None,
    agent_indices: dict[str, int] | None = None,
    version_context: dict | None = None,
    workflow_metadata: dict | None = None,
    current_item: dict | None = None,
    context_scope: dict | None = None,
) -> dict:
    """
    Build field context with explicit namespace structure.

    Composes focused builders for each concern: source data, dependency
    namespaces, version iteration info, and workflow metadata.

    Architecture (per anatomy_action.md):
    field_context = {
        "source": {...},        # Original input data — read from current_item["source"]
        "{dep_name}": {...},    # Dependency action outputs (FILTERED by context_scope)
        "seed": {...},          # Static reference data (via static_data)
        "version": {...},       # Version iteration info (i, idx, length, first, last)
        "workflow": {...},      # Workflow metadata
    }

    Args:
        agent_name: Name of the current action
        agent_config: Action configuration dict
        agent_indices: REQUIRED if action has dependencies. Maps action names to positions.
        version_context: Loop iteration info
        workflow_metadata: Workflow metadata
        current_item: Current record being processed. Must carry the source
            namespace at the top-level ``source`` field (set once at staging
            admission, propagated as a tracking field).
        context_scope: Controls which fields to load (progressive data exposure)

    Returns:
        Dict with namespaces: source, {dep_names}, version, workflow.
        May contain "_dependency_metadata" key with field-load diagnostics
        (callers needing it should pop it before passing downstream).

    Raises:
        ConfigurationError: If action has dependencies but agent_indices not provided
    """
    field_context: dict = {}

    _load_source_namespace(field_context, current_item, agent_name)
    _load_dependency_namespaces(
        field_context, agent_name, agent_config, agent_indices, current_item, context_scope
    )
    _load_version_context(field_context, version_context, agent_name)
    _load_workflow_metadata(field_context, workflow_metadata, agent_name)

    logger.debug(
        "Built field_context for '%s' with namespaces: %s",
        agent_name,
        list(field_context.keys()),
    )

    return field_context


def _load_source_namespace(field_context: dict, current_item: Any | None, agent_name: str) -> None:
    """Load the source namespace from the record envelope.

    The ``source`` field on the record envelope is the canonical, single source
    of truth for original-input data. It is set once at staging admission via
    ``RecordEnvelope.admit_staging_row`` (which hoists raw user fields under
    ``record["source"]``) and propagated by ``_carry_tracking_fields`` through
    every action — no duck-typing on shape, no list lookup, no fallback path.
    """
    if not isinstance(current_item, dict):
        return

    source_namespace = current_item.get("source")
    if not isinstance(source_namespace, dict) or not source_namespace:
        if current_item and "source" not in current_item:
            logger.warning(
                "Action '%s' received a record with no top-level 'source' field — "
                "staging admission may have been skipped",
                agent_name,
            )
        return

    field_context["source"] = source_namespace
    logger.debug("Added 'source' namespace with %s fields", len(source_namespace))
    fire_event(
        ContextNamespaceLoadedEvent(
            action_name=agent_name,
            namespace="source",
            field_count=len(source_namespace),
            fields=list(source_namespace.keys()),
        )
    )


def _load_dependency_namespaces(
    field_context: dict,
    agent_name: str,
    agent_config: dict | None,
    agent_indices: dict[str, int] | None,
    current_item: dict | None,
    context_scope: dict | None,
) -> None:
    """Load dependency action outputs from record's namespaced content.

    With the additive content model, every previous action's output is
    stored under its namespace on the record: content = {"action_a": {...}, ...}.

    Collects field-load metadata and stores it on field_context["_dependency_metadata"]
    for downstream diagnostics.
    """
    from agent_actions.utils.constants import SPECIAL_NAMESPACES

    batch_mode_enabled = bool(agent_config and agent_indices and current_item)
    logger.debug(
        "[CONTEXT BUILD] Action '%s': batch_mode_enabled=%s",
        agent_name,
        batch_mode_enabled,
    )

    if batch_mode_enabled:
        # Narrowed by batch_mode_enabled — all are truthy
        if agent_config is None or agent_indices is None or current_item is None:
            raise ValueError(
                f"batch_mode requires agent_config, agent_indices, and current_item "
                f"(action: '{agent_name}')"
            )

        workflow_actions = list(agent_indices.keys())
        input_sources, context_sources = infer_dependencies(
            agent_config, workflow_actions, agent_name, validate=False
        )

        logger.debug(
            "[AUTO-INFER] Action '%s': input_sources=%s, context_sources=%s",
            agent_name,
            input_sources,
            context_sources,
        )

        namespaced_content = _extract_content_data(current_item)
        all_deps = input_sources + context_sources
        metadata_collector: dict = {}

        if all_deps:
            allowed_fields_map = _extract_allowed_fields_per_dependency(
                all_deps, context_scope, agent_name
            )

            for dep_name in all_deps:
                if dep_name in SPECIAL_NAMESPACES:
                    logger.debug("Skipping special namespace '%s' (handled separately)", dep_name)
                    continue

                dep_data = namespaced_content.get(dep_name)
                if dep_data is None:
                    logger.debug(
                        "[RECORD NAMESPACE] '%s' not found on record for action '%s'",
                        dep_name,
                        agent_name,
                    )
                    continue

                if not isinstance(dep_data, dict):
                    logger.warning(
                        "[RECORD NAMESPACE] '%s' for action '%s' is %s, not dict — skipping",
                        dep_name,
                        agent_name,
                        type(dep_data).__name__,
                    )
                    continue

                allowed_fields = allowed_fields_map.get(dep_name)
                _filter_and_store_fields(
                    field_context,
                    dep_name,
                    dep_data,
                    allowed_fields,
                    source_type="RECORD NAMESPACE",
                    fail_on_missing=True,
                    metadata_collector=metadata_collector,
                )

        if metadata_collector:
            field_context["_dependency_metadata"] = metadata_collector

    else:
        logger.debug(
            "[CONTEXT BUILD SKIP] Action '%s': Batch mode condition not met.",
            agent_name,
        )

    if agent_config and agent_config.get("dependencies") and not agent_indices:
        dependencies = agent_config.get("dependencies", [])
        raise ConfigurationError(
            f"Action '{agent_name}' has dependencies {dependencies} but agent_indices was not provided. "
            f"agent_indices is required for dependency resolution.\n\n"
            f"Ensure the workflow orchestrator passes agent_indices to build_field_context_with_history().",
            context={
                "action": agent_name,
                "dependencies": dependencies,
                "hint": "agent_indices must be a dict mapping action names to their positions",
            },
        )


def _load_version_context(
    field_context: dict, version_context: dict | None, agent_name: str
) -> None:
    """Load version iteration info and promote convenience variables to top level."""
    if not version_context:
        return

    field_context["version"] = version_context
    # Add common version variables at top level for convenience
    # This enables {{ i }} instead of requiring {{ version.i }}
    if "i" in version_context:
        field_context["i"] = version_context["i"]
    if "idx" in version_context:
        field_context["idx"] = version_context["idx"]
    # Add custom param names at top level (e.g., {{ classifier_id }})
    reserved_keys = {"i", "idx", "length", "first", "last"}
    for key, value in version_context.items():
        if key not in reserved_keys:
            field_context[key] = value
    logger.debug("Added 'version' namespace with version context")
    fire_event(
        ContextNamespaceLoadedEvent(
            action_name=agent_name,
            namespace="version",
            field_count=len(version_context),
            fields=list(version_context.keys()),
        )
    )


def _load_workflow_metadata(
    field_context: dict, workflow_metadata: dict | None, agent_name: str
) -> None:
    """Load workflow metadata into the 'workflow' namespace."""
    if not workflow_metadata:
        return

    field_context["workflow"] = workflow_metadata
    logger.debug("Added 'workflow' namespace")
    fire_event(
        ContextNamespaceLoadedEvent(
            action_name=agent_name,
            namespace="workflow",
            field_count=len(workflow_metadata),
            fields=list(workflow_metadata.keys()),
        )
    )
