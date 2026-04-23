"""Field context builder — reads from record's namespaced content."""

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

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


# Complex field context building with historical data requires all these parameters
def build_field_context_with_history(
    agent_name: str,
    agent_config: dict | None,
    agent_indices: dict[str, int] | None = None,
    source_content: Any | None = None,
    version_context: dict | None = None,
    workflow_metadata: dict | None = None,
    current_item: dict | None = None,
    file_path: str | None = None,
    context_scope: dict | None = None,
    output_directory: str | None = None,
    storage_backend: Optional["StorageBackend"] = None,
    metadata_collector: dict | None = None,
) -> dict:
    """
    Build field context with explicit namespace structure.

    Additive content model: all dependency data lives on the record's
    namespaced content.  No storage backend lookup required.

    IMPORTANT: agent_indices is REQUIRED when action has dependencies.
    No fallbacks - this ensures consistent behavior across all execution modes.

    Architecture (per anatomy_action.md):
    field_context = {
        "source": {...},        # Original input data
        "{dep_name}": {...},    # Dependency action outputs (FILTERED by context_scope)
        "seed": {...},          # Static reference data (via static_data)
        "version": {...},       # Version iteration info (i, idx, length, first, last)
        "workflow": {...},      # Workflow metadata
    }

    Args:
        agent_name: Name of the current action
        agent_config: Action configuration dict
        agent_indices: REQUIRED if action has dependencies. Maps action names to positions.
        source_content: Original input data for "source" namespace
        version_context: Loop iteration info
        workflow_metadata: Workflow metadata
        current_item: Current record being processed (has lineage, content)
        file_path: Path to current file
        context_scope: Controls which fields to load (progressive data exposure)
        output_directory: Unused (legacy parameter retained for caller compatibility)
        storage_backend: Unused (legacy parameter retained for caller compatibility)

    Returns:
        Dict with namespaces: source, {dep_names}, version, workflow

    Raises:
        ConfigurationError: If action has dependencies but agent_indices not provided

    Progressive Data Exposure:
    - context_scope.observe: ["dep.field1", "dep.*"] -> Controls what gets loaded
    - context_scope.passthrough: ["dep.field2"] -> Also loaded (needed for output)
    - Undeclared fields never enter memory
    """
    from agent_actions.utils.constants import SPECIAL_NAMESPACES

    field_context = {}

    # 1. SOURCE namespace - original input data.
    # source_content is raw input (not a record), so we must not filter
    # _RECORD_METADATA_KEYS from it.  _extract_content_data is designed
    # for records; use it only to unwrap the {"content": {...}} wrapper.
    source_namespace: dict = {}
    if source_content and isinstance(source_content, dict):
        if "content" in source_content and isinstance(source_content["content"], dict):
            source_namespace = source_content["content"]
        else:
            source_namespace = dict(source_content)

    if source_namespace:
        field_context["source"] = source_namespace
        logger.debug("Added 'source' namespace with %s fields", len(field_context["source"]))
        fire_event(
            ContextNamespaceLoadedEvent(
                action_name=agent_name,
                namespace="source",
                field_count=len(source_namespace),
                fields=list(source_namespace.keys()),
            )
        )

    # 2. DEPENDENCY namespaces — read from record's namespaced content.
    # With the additive content model, every previous action's output is
    # stored under its namespace on the record: content = {"action_a": {...}, ...}.
    # No storage backend lookup required.
    batch_mode_enabled = bool(agent_config and agent_indices and current_item and file_path)
    logger.debug(
        "[CONTEXT BUILD] Action '%s': batch_mode_enabled=%s",
        agent_name,
        batch_mode_enabled,
    )
    if batch_mode_enabled:
        # Narrowed by batch_mode_enabled — all are truthy
        if agent_config is None:
            raise ValueError(
                f"agent_config must not be None when batch_mode is enabled (action: '{agent_name}')"
            )
        if agent_indices is None:
            raise ValueError(
                f"agent_indices must not be None when batch_mode is enabled (action: '{agent_name}')"
            )
        if current_item is None:
            raise ValueError(
                f"current_item must not be None when batch_mode is enabled (action: '{agent_name}')"
            )
        if file_path is None:
            raise ValueError(
                f"file_path must not be None when batch_mode is enabled (action: '{agent_name}')"
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

        # Additive model: all dependency data lives on the record.
        namespaced_content = _extract_content_data(current_item)
        all_deps = input_sources + context_sources

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
                    # Missing namespace: skipped action or not yet produced — not an error.
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

    else:
        logger.debug(
            "[CONTEXT BUILD SKIP] Action '%s': Batch mode condition not met.",
            agent_name,
        )

    if agent_config and agent_config.get("dependencies") and not agent_indices:
        # ERROR: Dependencies declared but no agent_indices provided
        # agent_indices is REQUIRED for dependency resolution (no fallbacks)
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

    # 3. VERSION namespace - iteration info (for version actions)
    # Provides {{ version.length }}, {{ version.first }}, {{ version.last }}
    # Also adds top-level {{ i }}, {{ idx }}, and custom param names
    if version_context:
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

    # 4. WORKFLOW namespace - metadata
    if workflow_metadata:
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

    logger.debug(
        "Built field_context for '%s' with namespaces: %s",
        agent_name,
        list(field_context.keys()),
    )

    return field_context
