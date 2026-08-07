"""Evaluation context building for guards, filters, and prompts."""

import logging
from dataclasses import dataclass, field
from typing import Any

from agent_actions.prompt.context.scope_builder import build_field_context_with_history

logger = logging.getLogger(__name__)


@dataclass
class ContextBuildConfig:
    """Configuration for building evaluation context."""

    agent_config: dict[str, Any]
    agent_name: str
    agent_indices: dict[str, int] | None = None
    dependency_configs: dict[str, dict] | None = None
    file_path: str | None = None
    source_content: Any | None = None
    version_context: dict[str, Any] | None = None
    workflow_metadata: dict[str, Any] | None = None


@dataclass
class EvaluationContext:
    """Rich context for guard/filter/prompt evaluation with upstream action access."""

    current_content: dict[str, Any]
    field_context: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_content: dict[str, Any] | None = None
    version_context: dict[str, Any] | None = None
    workflow_metadata: dict[str, Any] | None = None
    current_item: dict[str, Any] | None = None


class EvaluationContextProvider:
    """Builds rich evaluation contexts for guards, filters, and prompts."""

    def build_context(
        self, current_item: dict[str, Any], config: ContextBuildConfig
    ) -> EvaluationContext:
        """Build rich evaluation context for item-level operations."""
        current_content = current_item.get("content")
        if not isinstance(current_content, dict):
            current_content = {}

        context_scope = config.agent_config.get("context_scope")
        field_context = build_field_context_with_history(
            agent_name=config.agent_name,
            agent_config=config.agent_config,
            agent_indices=config.agent_indices,
            source_content=config.source_content,
            version_context=config.version_context,
            workflow_metadata=config.workflow_metadata,
            current_item=current_item,
            context_scope=context_scope,
        )
        field_context.pop("_dependency_metadata", None)

        return EvaluationContext(
            current_content=current_content,
            field_context=field_context,
            source_content=field_context.get("source"),
            version_context=field_context.get("version"),
            workflow_metadata=field_context.get("workflow"),
            current_item=current_item,
        )
