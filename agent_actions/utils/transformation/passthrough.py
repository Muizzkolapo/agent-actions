"""Orchestrator for passthrough transformations using the Strategy Pattern."""

from typing import Dict, List, Optional
from agent_actions.utils.field_management import FieldManager
from .strategies import (
    PrecomputedStructuredStrategy,
    PrecomputedUnstructuredStrategy,
    ContextScopeStructuredStrategy,
    ContextScopeUnstructuredStrategy,
    NoOpStrategy,
    DefaultStructureStrategy,
)


class PassthroughTransformer:
    """Orchestrates passthrough transformations using strategy pattern dispatch."""

    def __init__(self, field_manager: Optional[FieldManager] = None):
        """Initialize with an optional FieldManager (defaults to a new instance)."""
        self.field_manager = field_manager or FieldManager()

        # First match wins, so order matters
        self.strategies = [
            PrecomputedStructuredStrategy(),
            PrecomputedUnstructuredStrategy(),
            ContextScopeStructuredStrategy(),
            ContextScopeUnstructuredStrategy(),
            NoOpStrategy(),
            DefaultStructureStrategy(),  # Catch-all
        ]

    def transform_with_passthrough(
        self,
        data: List,
        context_data: Dict,
        source_guid: str,
        agent_config: Dict,
        action_name: str = "unknown_action",
        passthrough_fields: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
    ) -> List:
        """Apply context_scope.passthrough logic to generated data.

        Merges passthrough fields into output items using the appropriate
        strategy, then ensures all items have required fields.

        Args:
            data: Generated data list.
            context_data: Context data dictionary containing fields.
            source_guid: Source GUID.
            agent_config: Agent configuration containing context_scope.
            action_name: Action name for node_id generation.
            passthrough_fields: Optional pre-computed passthrough fields
                from field_context (enables passthrough from any ancestor).
            metadata: Optional LLM response metadata to add to output items.

        Returns:
            Transformed data list with passthrough fields merged.
        """
        if not isinstance(data, list):
            data = [data] if data is not None else []

        already_structured = self._is_already_structured(data)

        output = None
        for strategy in self.strategies:
            if strategy.can_handle(data, passthrough_fields, agent_config, already_structured):
                output = strategy.transform(
                    data, context_data, source_guid, agent_config, passthrough_fields
                )
                break

        return [
            self.field_manager.ensure_required_fields(
                obj, source_guid, action_name, metadata=metadata
            )
            for obj in output
        ]

    @staticmethod
    def _is_already_structured(data: List) -> bool:
        """Check if every item has ``source_guid`` and ``content`` keys."""
        return len(data) > 0 and all(
            isinstance(item, dict) and "source_guid" in item and "content" in item for item in data
        )
