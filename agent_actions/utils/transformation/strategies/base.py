"""Interface for passthrough transformation strategies."""

from abc import ABC, abstractmethod


class IPassthroughTransformStrategy(ABC):
    """Interface for passthrough transformation strategies."""

    @abstractmethod
    def can_handle(
        self,
        data: list,
        passthrough_fields: dict | None,
        agent_config: dict,
        already_structured: bool,
    ) -> bool:
        """Check if this strategy can handle the given inputs."""

    @abstractmethod
    def transform(
        self,
        data: list,
        context_data: dict,
        source_guid: str,
        agent_config: dict,
        passthrough_fields: dict | None = None,
    ) -> list:
        """Execute the transformation and return the transformed data list."""
