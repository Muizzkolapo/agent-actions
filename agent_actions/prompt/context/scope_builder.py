"""Field context builder with historical data loading."""

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

from agent_actions.errors import ConfigurationError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.io_events import ContextNamespaceLoadedEvent
from agent_actions.prompt.context.scope_inference import infer_dependencies
from agent_actions.prompt.context.scope_namespace import (
    _detect_version_namespaces,
    _enrich_source_namespace,
    _extract_allowed_fields_per_dependency,
    _extract_content_data,
    _filter_and_store_fields,
    _load_historical_node,
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

    AUTO-INFERRED CONTEXT DEPENDENCIES:
    - Input sources (from dependencies field): Data already in current_item
    - Context sources (auto-inferred from context_scope): Loaded via historical loader

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
        output_directory: Optional output directory (legacy, unused)
        storage_backend: Optional storage backend for loading historical data from SQLite/TinyDB

    Returns:
        Dict with namespaces: source, {dep_names}, version, workflow

    Raises:
        ConfigurationError: If action has dependencies but agent_indices not provided

    Progressive Data Exposure:
    - context_scope.observe: ["dep.field1", "dep.*"] -> Controls what gets loaded
    - context_scope.passthrough: ["dep.field2"] -> Also loaded (needed for output)
    - Undeclared fields never enter memory
    """
    from agent_actions.input.context.historical import (
        HistoricalNodeDataLoader,
    )
    from agent_actions.utils.constants import SPECIAL_NAMESPACES

    field_context = {}

    # 1. SOURCE namespace - original input data
    source_namespace = {}
    if source_content:
        source_namespace = _extract_content_data(source_content)

    source_namespace = _enrich_source_namespace(source_namespace, current_item)

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

    # 2. DEPENDENCY namespaces - separate input sources from context sources
    logger.debug(
        "[CONTEXT BUILD] Action '%s': agent_config=%s, agent_indices=%s, current_item=%s, file_path=%s",
        agent_name,
        bool(agent_config),
        len(agent_indices) if agent_indices else 0,
        bool(current_item),
        bool(file_path),
    )
    batch_mode_enabled = bool(agent_config and agent_indices and current_item and file_path)
    logger.debug(
        "[CONTEXT BUILD] Action '%s': batch_mode_enabled=%s (config=%s, indices=%s, item=%s, path=%s)",
        agent_name,
        batch_mode_enabled,
        bool(agent_config),
        bool(agent_indices),
        bool(current_item),
        bool(file_path),
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

        # BATCH MODE - Use auto-inferred context dependencies
        workflow_actions = list(agent_indices.keys())

        # Infer input sources vs context sources
        input_sources, context_sources = infer_dependencies(
            agent_config, workflow_actions, agent_name
        )

        logger.debug(
            "[AUTO-INFER] Action '%s': input_sources=%s, context_sources=%s",
            agent_name,
            input_sources,
            context_sources,
        )

        lineage = current_item.get("lineage", [])
        source_guid = current_item.get("source_guid")
        current_idx = agent_indices.get(agent_name, 999)
        allowed_fields_map = None

        # 2a. INPUT SOURCES - Data is already in current_item (the file being processed)
        # Put it under the action name so prompts can reference {{ action_name.field }}
        if input_sources and current_item:
            input_data = _extract_content_data(current_item)

            # Get allowed fields for input sources
            all_deps_for_fields = input_sources + context_sources
            allowed_fields_map = _extract_allowed_fields_per_dependency(
                all_deps_for_fields, context_scope, agent_name
            )

            # Check if input_data contains nested version namespaces from version_consumption
            # This happens when upstream action used version_consumption with merge pattern
            # Structure: {version_1: {fields}, version_2: {fields}, ...}
            version_namespaces_detected = _detect_version_namespaces(input_data, input_sources)

            if version_namespaces_detected:
                # Split nested version namespaces into separate top-level namespaces
                logger.debug(
                    "[VERSION NAMESPACES] Detected nested version namespaces in input_data: %s",
                    version_namespaces_detected,
                )

                for version_name, version_data in input_data.items():
                    if not isinstance(version_data, dict):
                        # Not a version namespace, skip
                        continue

                    if version_name not in version_namespaces_detected:
                        # Not a detected version namespace, skip
                        continue

                    # Add as separate namespace in field_context
                    allowed_fields = allowed_fields_map.get(version_name)
                    _filter_and_store_fields(
                        field_context,
                        version_name,
                        version_data,
                        allowed_fields,
                        source_type="VERSION NAMESPACE",
                        metadata_collector=metadata_collector,
                    )

                # Load parallel version sources via historical lookup
                # When input_sources has multiple versioned branches (e.g., action_1, action_2),
                # current_item only contains data from one. Load others from historical data.
                parallel_version_sources = [
                    src
                    for src in input_sources
                    if src not in field_context and src in agent_indices
                ]
                if parallel_version_sources and source_guid:
                    logger.debug(
                        "[PARALLEL VERSIONS] Loading %d parallel version sources "
                        "via historical lookup: %s",
                        len(parallel_version_sources),
                        parallel_version_sources,
                    )
                    for version_source in parallel_version_sources:
                        version_idx = agent_indices.get(version_source)
                        if version_idx is None or version_idx >= current_idx:
                            continue

                        try:
                            historical_data = _load_historical_node(
                                action_name=version_source,
                                lineage=lineage,
                                source_guid=source_guid or "",
                                file_path=file_path,
                                agent_indices=agent_indices,
                                parent_target_id=current_item.get("parent_target_id"),
                                root_target_id=current_item.get("root_target_id"),
                                output_directory=output_directory,
                                storage_backend=storage_backend,
                                lineage_sources=current_item.get("lineage_sources"),
                            )
                        except (ValueError, TypeError, KeyError):
                            logger.warning(
                                "Failed to load historical data for version source '%s'",
                                version_source,
                                exc_info=True,
                            )
                            historical_data = None

                        if historical_data:
                            allowed_fields = allowed_fields_map.get(version_source)
                            _filter_and_store_fields(
                                field_context,
                                version_source,
                                historical_data,
                                allowed_fields,
                                source_type="PARALLEL VERSION",
                                metadata_collector=metadata_collector,
                            )
                        else:
                            logger.warning(
                                "[PARALLEL VERSION] Could not load '%s' "
                                "via historical lookup. source_guid=%s",
                                version_source,
                                source_guid,
                            )
            else:
                # No version namespaces detected - use original behavior
                logger.debug(
                    "[INPUT SOURCE] input_data keys: %s",
                    list(input_data.keys()) if input_data else "EMPTY",
                )
                for input_source_name in input_sources:
                    allowed_fields = allowed_fields_map.get(input_source_name)
                    logger.debug(
                        "[INPUT SOURCE] '%s': allowed_fields=%s",
                        input_source_name,
                        allowed_fields,
                    )
                    _filter_and_store_fields(
                        field_context,
                        input_source_name,
                        input_data,
                        allowed_fields,
                        source_type="INPUT SOURCE",
                        fail_on_missing=True,
                        metadata_collector=metadata_collector,
                    )

        # 2b. CONTEXT SOURCES - Load via historical loader (lineage matching)
        logger.debug(
            "[CONTEXT SOURCES CHECK] Action '%s': context_sources=%s, will load=%s",
            agent_name,
            context_sources,
            bool(context_sources),
        )
        if context_sources:
            # Get allowed fields for context sources
            if allowed_fields_map is None:
                all_deps_for_fields = input_sources + context_sources
                allowed_fields_map = _extract_allowed_fields_per_dependency(
                    all_deps_for_fields, context_scope, agent_name
                )

            logger.debug(
                "[CONTEXT SOURCES] Loading %d context dependencies: %s (storage_backend=%s)",
                len(context_sources),
                context_sources,
                "available" if storage_backend else "NOT available",
            )

            for dep_name in context_sources:
                # Skip special reserved namespaces - they're populated differently
                if dep_name in SPECIAL_NAMESPACES:
                    logger.debug("Skipping special namespace '%s' (handled separately)", dep_name)
                    continue

                # Check if dependency should be loaded
                dep_idx = agent_indices.get(dep_name)
                if dep_idx is None:
                    logger.warning(
                        "Context dependency '%s' not found in agent_indices. Available: %s",
                        dep_name,
                        list(agent_indices.keys()),
                    )
                    continue

                if dep_idx >= current_idx:
                    logger.debug(
                        "Skipping context dependency '%s' (comes after current action)",
                        dep_name,
                    )
                    continue

                # Parallel Branch Check (uses same disambiguation as the matcher)
                is_ancestor = (
                    HistoricalNodeDataLoader._find_target_node_id(
                        dep_name, lineage, agent_indices=agent_indices
                    )
                    is not None
                )

                if not is_ancestor:
                    logger.debug(
                        "Context dependency '%s' not in lineage (may not have executed yet). "
                        "Will attempt to load from historical files.",
                        dep_name,
                    )

                # Load historical data
                logger.debug(
                    "[HISTORICAL LOAD] Loading context dep '%s' from file_path=%s",
                    dep_name,
                    file_path,
                )
                try:
                    historical_data = _load_historical_node(
                        action_name=dep_name,
                        lineage=lineage,
                        source_guid=source_guid or "",
                        file_path=file_path,
                        agent_indices=agent_indices,
                        parent_target_id=current_item.get("parent_target_id"),
                        root_target_id=current_item.get("root_target_id"),
                        output_directory=output_directory,
                        storage_backend=storage_backend,
                        lineage_sources=current_item.get("lineage_sources"),
                    )
                except (ValueError, TypeError, KeyError):
                    logger.warning(
                        "Failed to load historical data for context dep '%s'",
                        dep_name,
                        exc_info=True,
                    )
                    historical_data = None

                logger.debug(
                    "[HISTORICAL] Action '%s': dep='%s' -> %s",
                    agent_name,
                    dep_name,
                    "FOUND" if historical_data else "NOT FOUND",
                )
                if historical_data is None:
                    logger.warning(
                        "[CONTEXT SOURCE] Context dependency '%s' historical data not found. "
                        "Lineage: %s, source_guid: %s. "
                        "Dependency will not be available in field_context.",
                        dep_name,
                        lineage,
                        source_guid,
                    )
                    continue

                logger.debug(
                    "[HISTORICAL LOAD] Loaded context dep '%s': fields=%s",
                    dep_name,
                    list(historical_data.keys()),
                )

                # PROGRESSIVE DATA EXPOSURE: Filter to only allowed fields
                allowed_fields = allowed_fields_map.get(dep_name)
                _filter_and_store_fields(
                    field_context,
                    dep_name,
                    historical_data,
                    allowed_fields,
                    source_type="CONTEXT SOURCE",
                    fail_on_missing=True,
                    metadata_collector=metadata_collector,
                )

    else:
        # Log why batch mode condition wasn't met
        logger.debug(
            "[CONTEXT BUILD SKIP] Action '%s': Batch mode condition not met. "
            "agent_config=%s, agent_indices=%s, current_item=%s, file_path=%s",
            agent_name,
            bool(agent_config),
            len(agent_indices) if agent_indices else 0,
            bool(current_item),
            bool(file_path),
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
