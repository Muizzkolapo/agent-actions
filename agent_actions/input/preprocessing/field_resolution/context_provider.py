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

    def get_action_output(self, action_name: str) -> dict[str, Any] | None:
        """Get output from a specific upstream action."""
        return self.field_context.get(action_name)

    def has_action(self, action_name: str) -> bool:
        """Check if an action's output exists in context."""
        return action_name in self.field_context

    def get_field_value(self, action_name: str, field_name: str, default: Any = None) -> Any:
        """Get a specific field from an action's output."""
        action_data = self.get_action_output(action_name)
        if action_data and isinstance(action_data, dict):
            return action_data.get(field_name, default)
        return default

    def to_flat_dict(self) -> dict[str, Any]:
        """Convert to flat dict for WHERE clause evaluation."""
        flat = {}

        if self.current_content:
            flat.update(self.current_content)

        for action_name, action_data in self.field_context.items():
            if action_name not in flat:
                flat[action_name] = action_data

        if self.source_content and "source" not in flat:
            flat["source"] = self.source_content

        if self.version_context and "version" not in flat:
            flat["version"] = self.version_context

        if self.workflow_metadata and "workflow" not in flat:
            flat["workflow"] = self.workflow_metadata

        return flat

    def to_nested_dict(self) -> dict[str, Any]:
        """Get the full nested field_context structure."""
        return self.field_context.copy()


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
            file_path=config.file_path,
            context_scope=context_scope,
        )

        return EvaluationContext(
            current_content=current_content,
            field_context=field_context,
            source_content=field_context.get("source"),
            version_context=field_context.get("version"),
            workflow_metadata=field_context.get("workflow"),
            current_item=current_item,
        )

    def build_context_for_batch(
        self,
        contents: dict[str, Any],
        config: ContextBuildConfig,
        current_item: dict[str, Any] | None = None,
    ) -> EvaluationContext:
        """Build context for batch mode (simplified parameters)."""
        if current_item is None:
            current_item = {
                "content": contents,
                "source_guid": contents.get("source_guid") if contents else None,
                "lineage": contents.get("lineage", []) if contents else [],
            }

        return self.build_context(current_item=current_item, config=config)

    def build_minimal_context(
        self,
        current_content: dict[str, Any],
        upstream_data: dict[str, dict[str, Any]] | None = None,
    ) -> EvaluationContext:
        """Build minimal context without historical loading."""
        return EvaluationContext(
            current_content=current_content,
            field_context=upstream_data or {},
            current_item={"content": current_content},
        )
