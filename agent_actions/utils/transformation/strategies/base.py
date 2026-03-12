"""Interface for passthrough transformation strategies."""

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
        already_structured: bool,
    ) -> bool:
        """Check if this strategy can handle the given inputs."""

    @abstractmethod
    def transform(
        self,
        data: List,
        context_data: Dict,
        source_guid: str,
        agent_config: Dict,
        passthrough_fields: Optional[Dict] = None,
    ) -> List:
        """Execute the transformation and return the transformed data list."""
