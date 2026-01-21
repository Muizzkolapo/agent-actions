"""
Passthrough Transformation Service.

This module provides the main orchestrator for passthrough transformations
using a Strategy Pattern to handle different transformation scenarios.
"""

from typing import Dict, List, Optional
from agent_actions.utilities.field_management import FieldManager
from .strategies import (
    PrecomputedStructuredStrategy,
    PrecomputedUnstructuredStrategy,
    ContextScopeStructuredStrategy,
    ContextScopeUnstructuredStrategy,
    NoOpStrategy,
    DefaultStructureStrategy,
)


class PassthroughTransformer:
    """
    Orchestrates passthrough transformations using Strategy Pattern.

    Applies context_scope.passthrough logic to generated data using
    specialized strategies for different scenarios:
    - Precomputed fields (from field_context)
    - Context scope extraction (from context_scope.passthrough config)
    - Structured vs unstructured data

    Note: Single public method is appropriate for transformer orchestrator pattern.
    """

    def __init__(self, field_manager: Optional[FieldManager] = None):
        """
        Initialize the transformer.

        Args:
            field_manager: Optional field manager for ensuring required
                          fields. If not provided, creates a new instance.
        """
        self.field_manager = field_manager or FieldManager()

        # Register strategies in priority order
        # First match wins, so order matters!
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
        idx: int = 0,
        passthrough_fields: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
    ) -> List:
        """
        Apply context_scope.passthrough logic to generated data.

        context_scope.passthrough specifies fields from upstream actions:
        - Excluded from the LLM prompt and context
        - Included in the final output (passthrough to next agent)
        - Uses {action.field} syntax (e.g., 'extractor.document_id')

        Args:
            data: Generated data list
            context_data: Context data dictionary containing fields
            source_guid: Source GUID
            agent_config: Agent configuration containing context_scope
            idx: Index for node generation
            passthrough_fields: Optional pre-computed passthrough fields
                               from field_context. If provided, these
                               values will be used instead of extracting
                               from context_data. This enables passthrough
                               from ANY previous action (not just immediate
                               predecessor).
            metadata: Optional LLM response metadata to add to output items

        Returns:
            Transformed data list with passthrough fields merged
        """
        # Step 1: Normalize data to list
        if not isinstance(data, list):
            data = [data] if data is not None else []

        # Step 2: Detect if data is already structured
        already_structured = self._is_already_structured(data)

        # Step 3: Select and execute strategy
        output = None
        for strategy in self.strategies:
            if strategy.can_handle(data, passthrough_fields, agent_config, already_structured):
                output = strategy.transform(
                    data, context_data, source_guid, agent_config, passthrough_fields
                )
                break

        # Step 4: Ensure all items have required fields and add metadata
        return [
            self.field_manager.ensure_required_fields(obj, source_guid, idx, metadata=metadata)
            for obj in output
        ]

    @staticmethod
    def _is_already_structured(data: List) -> bool:
        """
        Check if data is already structured.

        Structured format: [{'source_guid': ..., 'content': ...}, ...]

        Args:
            data: Data list to check

        Returns:
            True if data is already in structured format
        """
        return len(data) > 0 and all(
            isinstance(item, dict) and "source_guid" in item and "content" in item for item in data
        )
