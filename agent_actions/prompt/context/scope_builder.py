"""Field context builder — reads from record's namespaced content.

Assembles field_context from four composable namespace builders:
- SourceNamespaceBuilder: user input data
- DependencyNamespaceBuilder: upstream action outputs
- VersionNamespaceBuilder: loop iteration info + promoted convenience vars
- WorkflowMetadataBuilder: workflow-level metadata
"""

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


# ---------------------------------------------------------------------------
# Namespace builders
# ---------------------------------------------------------------------------


class SourceNamespaceBuilder:
    """Build the 'source' namespace from input data."""

    @staticmethod
    def build(source_content: Any | None, agent_name: str) -> dict | None:
        """Return source namespace dict, or None if no source data.

        Handles both wrapped (``{"content": {...}}``) and flat dict formats.
        Fires ContextNamespaceLoadedEvent on success.
        """
        source_namespace: dict = {}
        if source_content and isinstance(source_content, dict):
            if "content" in source_content and isinstance(source_content["content"], dict):
                source_namespace = source_content["content"]
            else:
                source_namespace = dict(source_content)

        if not source_namespace:
            return None

        logger.debug("Added 'source' namespace with %s fields", len(source_namespace))
        fire_event(
            ContextNamespaceLoadedEvent(
                action_name=agent_name,
                namespace="source",
                field_count=len(source_namespace),
                fields=list(source_namespace.keys()),
            )
        )
        return source_namespace


class DependencyNamespaceBuilder:
    """Build dependency namespaces from record's namespaced content."""

    @staticmethod
    def build(
        agent_name: str,
        agent_config: dict | None,
        agent_indices: dict[str, int] | None,
        current_item: dict | None,
        context_scope: dict | None,
    ) -> tuple[dict[str, Any], dict]:
        """Return (dep_namespaces, metadata).

        dep_namespaces maps dep_name -> filtered data (or None for guard-skipped).
        metadata maps dep_name -> {stored_fields, loaded_fields, stored_count, loaded_count}.

        Raises:
            ConfigurationError: If action has dependencies but agent_indices not provided.
        """
        from agent_actions.utils.constants import SPECIAL_NAMESPACES

        dep_namespaces: dict[str, Any] = {}
        metadata_collector: dict = {}

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

            if all_deps:
                allowed_fields_map = _extract_allowed_fields_per_dependency(
                    all_deps, context_scope, agent_name
                )

                for dep_name in all_deps:
                    if dep_name in SPECIAL_NAMESPACES:
                        logger.debug(
                            "Skipping special namespace '%s' (handled separately)", dep_name
                        )
                        continue

                    dep_data = namespaced_content.get(dep_name)
                    if dep_data is None:
                        # Namespace is null (guard-skipped) or absent (guard-filtered /
                        # arrived via a different branch).  Store None so downstream
                        # observe/passthrough can distinguish "declared but absent" from
                        # "undeclared" and yield None instead of crashing.
                        logger.debug(
                            "[RECORD NAMESPACE] '%s' null/absent on record for action '%s' "
                            "(likely guard-skipped or guard-filtered)",
                            dep_name,
                            agent_name,
                        )
                        dep_namespaces[dep_name] = None
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
                        dep_namespaces,
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

        # ConfigurationError: MUST remain after batch-mode branch.
        # Fires when deps are declared but agent_indices is missing.
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

        return dep_namespaces, metadata_collector


class VersionNamespaceBuilder:
    """Build the 'version' namespace and promote convenience variables."""

    _RESERVED_KEYS = frozenset({"i", "idx", "length", "first", "last"})

    @staticmethod
    def build(version_context: dict | None, agent_name: str) -> dict | None:
        """Return dict with 'version' namespace and promoted top-level keys, or None.

        Promotes ``i`` and ``idx`` to top level for Jinja2 convenience
        (``{{ i }}`` instead of ``{{ version.i }}``). Custom params (non-reserved)
        are also promoted to top level.

        Fires ContextNamespaceLoadedEvent on success.
        """
        if not version_context:
            return None

        result: dict = {"version": version_context}

        # Promote i/idx to top level for Jinja2 convenience
        if "i" in version_context:
            result["i"] = version_context["i"]
        if "idx" in version_context:
            result["idx"] = version_context["idx"]

        # Promote custom param names (e.g., {{ classifier_id }})
        for key, value in version_context.items():
            if key not in VersionNamespaceBuilder._RESERVED_KEYS:
                result[key] = value

        logger.debug("Added 'version' namespace with version context")
        fire_event(
            ContextNamespaceLoadedEvent(
                action_name=agent_name,
                namespace="version",
                field_count=len(version_context),
                fields=list(version_context.keys()),
            )
        )
        return result


class WorkflowMetadataBuilder:
    """Build the 'workflow' namespace from workflow metadata."""

    @staticmethod
    def build(workflow_metadata: dict | None, agent_name: str) -> dict | None:
        """Return workflow namespace dict, or None if no metadata.

        Fires ContextNamespaceLoadedEvent on success.
        """
        if not workflow_metadata:
            return None

        logger.debug("Added 'workflow' namespace")
        fire_event(
            ContextNamespaceLoadedEvent(
                action_name=agent_name,
                namespace="workflow",
                field_count=len(workflow_metadata),
                fields=list(workflow_metadata.keys()),
            )
        )
        return workflow_metadata


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------


def build_field_context_with_history(
    agent_name: str,
    agent_config: dict | None,
    agent_indices: dict[str, int] | None = None,
    source_content: Any | None = None,
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
        context_scope: Controls which fields to load (progressive data exposure)

    Returns:
        Dict with namespaces: source, {dep_names}, version, workflow.
        May contain "_dependency_metadata" key with field-load diagnostics
        (callers needing it should pop it before passing downstream).

    Raises:
        ConfigurationError: If action has dependencies but agent_indices not provided
    """
    field_context: dict = {}

    source_ns = SourceNamespaceBuilder.build(source_content, agent_name)
    if source_ns:
        field_context["source"] = source_ns

    dep_namespaces, dep_metadata = DependencyNamespaceBuilder.build(
        agent_name, agent_config, agent_indices, current_item, context_scope
    )
    field_context.update(dep_namespaces)
    if dep_metadata:
        field_context["_dependency_metadata"] = dep_metadata

    version_result = VersionNamespaceBuilder.build(version_context, agent_name)
    if version_result:
        field_context.update(version_result)

    workflow_ns = WorkflowMetadataBuilder.build(workflow_metadata, agent_name)
    if workflow_ns:
        field_context["workflow"] = workflow_ns

    logger.debug(
        "Built field_context for '%s' with namespaces: %s",
        agent_name,
        list(field_context.keys()),
    )

    return field_context
