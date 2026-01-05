"""
Service for building rich evaluation contexts for guards, filters, and prompts.

Bridges the existing ContextScopeProcessor infrastructure with guard/filter evaluation
by providing unified access to all upstream action data.

The key insight is that ContextScopeProcessor.build_field_context_with_history() already
auto-loads ALL upstream action data - this module makes that data accessible to guards
and filters which previously only had access to current item content.

Example:
    provider = EvaluationContextProvider()

    # Build context for guard evaluation
    context = provider.build_context(
        current_item=item,
        agent_config=config,
        agent_name='my_action',
        agent_indices={'extract': 0, 'my_action': 1},
        file_path='/path/to/target'
    )

    # Now guards can access upstream fields!
    # WHERE clause: "extract.count > 5" will work!
    eval_data = context.to_flat_dict()
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from agent_actions.utilities.context_scope.context_scope_processor import ContextScopeProcessor

logger = logging.getLogger(__name__)


@dataclass
class ContextBuildConfig:
    """Configuration for building evaluation context."""

    agent_config: Dict[str, Any]
    agent_name: str
    agent_indices: Optional[Dict[str, int]] = None
    dependency_configs: Optional[Dict[str, Dict]] = None
    file_path: Optional[str] = None
    source_content: Optional[Any] = None
    loop_context: Optional[Dict[str, Any]] = None
    workflow_metadata: Optional[Dict[str, Any]] = None


@dataclass
class EvaluationContext:
    """
    Rich context for guard/filter/prompt evaluation.

    Provides access to:
    - Current item content (what was previously the only context available)
    - All upstream action outputs (NEW: enables direct field access in guards)
    - Source data
    - Loop context
    - Workflow metadata

    Attributes:
        current_content: Content of the current item being evaluated
        field_context: All upstream action outputs {action_name: {field: value}}
        source_content: Source data (if available)
        loop_context: Loop metadata (if in a loop)
        workflow_metadata: Workflow-level metadata
        current_item: Full item with lineage and metadata
    """

    current_content: Dict[str, Any]
    field_context: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    source_content: Optional[Dict[str, Any]] = None
    loop_context: Optional[Dict[str, Any]] = None
    workflow_metadata: Optional[Dict[str, Any]] = None
    current_item: Optional[Dict[str, Any]] = None

    def get_action_output(self, action_name: str) -> Optional[Dict[str, Any]]:
        """Get output from a specific upstream action."""
        return self.field_context.get(action_name)

    def has_action(self, action_name: str) -> bool:
        """Check if an action's output exists in context."""
        return action_name in self.field_context

    def get_field_value(self, action_name: str, field_name: str, default: Any = None) -> Any:
        """
        Get a specific field from an action's output.

        Args:
            action_name: Name of the upstream action
            field_name: Name of the field to retrieve
            default: Value to return if not found

        Returns:
            Field value or default
        """
        action_data = self.get_action_output(action_name)
        if action_data and isinstance(action_data, dict):
            return action_data.get(field_name, default)
        return default

    def to_flat_dict(self) -> Dict[str, Any]:
        """
        Convert to flat dict for backward compatibility with WHERE clause evaluator.

        The resulting dict has:
        - Current item content at the top level
        - Upstream action data under their action names (for action.field access)
        - Special contexts under their namespaces (source, loop, workflow)

        This enables WHERE clauses like:
        - "extract_facts.count > 5" (upstream field)
        - "status == 'active'" (current item field)
        - "source.type == 'pdf'" (source data)
        """
        flat = {}

        # Add current item content at top level (backward compatibility)
        if self.current_content:
            flat.update(self.current_content)

        # Add upstream action data under action names
        # This enables "action_name.field" access in WHERE clauses
        for action_name, action_data in self.field_context.items():
            if action_name not in flat:  # Don't overwrite current content
                flat[action_name] = action_data

        # Add special contexts
        if self.source_content and "source" not in flat:
            flat["source"] = self.source_content

        if self.loop_context and "loop" not in flat:
            flat["loop"] = self.loop_context

        if self.workflow_metadata and "workflow" not in flat:
            flat["workflow"] = self.workflow_metadata

        return flat

    def to_nested_dict(self) -> Dict[str, Any]:
        """
        Get the full nested structure (field_context).

        Useful when you need the complete context structure without flattening.
        """
        return self.field_context.copy()


class EvaluationContextProvider:
    """
    Service for building rich evaluation contexts for guards, filters, and prompts.

    Leverages existing ContextScopeProcessor.build_field_context_with_history()
    to auto-load all upstream action data, making it available to guards and filters.

    Example:
        provider = EvaluationContextProvider()

        # Build context for item-level guard evaluation
        context = provider.build_context(
            current_item={'content': {...}, 'source_guid': '...', 'lineage': [...]},
            agent_config={'agent_type': 'my_action', 'dependencies': ['extract']},
            agent_name='my_action',
            agent_indices={'extract': 0, 'my_action': 1},
            file_path='/path/to/target/node_1_my_action/file.json'
        )

        # Guards can now access upstream fields!
        eval_data = context.to_flat_dict()
        # eval_data['extract']['count'] is accessible for "extract.count > 5"
    """

    def build_context(
        self, current_item: Dict[str, Any], config: ContextBuildConfig
    ) -> EvaluationContext:
        """
        Build rich evaluation context for item-level operations.

        This is THE integration point - builds field_context with ALL upstream
        action data using existing ContextScopeProcessor infrastructure.

        Args:
            current_item: Current item being evaluated (expects 'content', 'source_guid', 'lineage')
            config: ContextBuildConfig with agent configuration and context parameters

        Returns:
            EvaluationContext with full upstream access
        """
        # Extract current content
        current_content = current_item.get("content", {})
        if not isinstance(current_content, dict):
            current_content = {}

        # Build field context using existing infrastructure
        # This auto-loads ALL upstream actions via historical node loader!
        try:
            field_context = ContextScopeProcessor.build_field_context_with_history(
                contents=current_content,
                agent_name=config.agent_name,
                agent_config=config.agent_config,
                agent_indices=config.agent_indices,
                dependency_configs=config.dependency_configs,
                source_content=config.source_content,
                loop_context=config.loop_context,
                workflow_metadata=config.workflow_metadata,
                current_item=current_item,
                file_path=config.file_path,
            )
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(
                "Error building field context for '%s': %s. Using empty context.",
                config.agent_name,
                e,
            )
            field_context = {}

        return EvaluationContext(
            current_content=current_content,
            field_context=field_context,
            source_content=field_context.get("source"),
            loop_context=field_context.get("loop"),
            workflow_metadata=field_context.get("workflow"),
            current_item=current_item,
        )

    def build_context_for_batch(
        self,
        contents: Dict[str, Any],
        config: ContextBuildConfig,
        current_item: Optional[Dict[str, Any]] = None,
    ) -> EvaluationContext:
        """
        Build context for batch mode (simplified parameters).

        Batch mode may not have current_item initially, so handle gracefully.

        Args:
            contents: Content dict of the current item
            config: ContextBuildConfig with agent configuration
            current_item: Full item (optional, built from contents if not provided)

        Returns:
            EvaluationContext with available upstream data
        """
        # Build minimal current_item if not provided
        if current_item is None:
            current_item = {
                "content": contents,
                "source_guid": contents.get("source_guid") if contents else None,
                "lineage": contents.get("lineage", []) if contents else [],
            }

        return self.build_context(current_item=current_item, config=config)

    def build_minimal_context(
        self,
        current_content: Dict[str, Any],
        upstream_data: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> EvaluationContext:
        """
        Build minimal context without historical loading.

        Useful for testing or when historical data is already available.

        Args:
            current_content: Current item content
            upstream_data: Pre-loaded upstream action data

        Returns:
            EvaluationContext with provided data
        """
        return EvaluationContext(
            current_content=current_content,
            field_context=upstream_data or {},
            current_item={"content": current_content},
        )
