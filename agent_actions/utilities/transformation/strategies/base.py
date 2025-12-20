"""
Base Strategy Interface for Passthrough Transformation.

This module defines the interface that all passthrough transformation
strategies must implement.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class IPassthroughTransformStrategy(ABC):
    """Interface for passthrough transformation strategies."""

    @abstractmethod
    def can_handle(
        self,
        data: List,
        passthrough_fields: Optional[Dict],
        agent_config: Dict,
        already_structured: bool
    ) -> bool:
        """
        Check if this strategy can handle the given inputs.

        Args:
            data: Data list to transform
            passthrough_fields: Optional pre-computed passthrough fields
            agent_config: Agent configuration
            already_structured: Whether data is already structured

        Returns:
            True if this strategy can handle the transformation
        """

    @abstractmethod
    def transform(
        self,
        data: List,
        context_data: Dict,
        source_guid: str,
        agent_config: Dict,
        passthrough_fields: Optional[Dict] = None
    ) -> List:
        """
        Execute the transformation.

        Args:
            data: Data list to transform
            context_data: Context data dictionary
            source_guid: Source GUID
            agent_config: Agent configuration
            passthrough_fields: Optional pre-computed passthrough fields

        Returns:
            Transformed data list
        """
