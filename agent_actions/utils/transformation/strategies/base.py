"""Interface for passthrough transformation strategies."""

from abc import ABC, abstractmethod
from typing import Any


def ensure_dict_output(item: Any) -> dict:
    """Normalize a strategy output item to a dict.

    Non-dict values are wrapped as ``{"value": item}`` so that
    ``RecordEnvelope.build()`` always receives a dict.
    """
    return item if isinstance(item, dict) else {"value": item}


class IPassthroughTransformStrategy(ABC):
    """Interface for passthrough transformation strategies.

    All strategies return ``list[dict]`` — flat action output dicts
    containing only the fields belonging to the action's namespace.
    ``PassthroughTransformer`` handles namespace wrapping and upstream
    preservation via ``RecordEnvelope.build()``.
    """

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
        """Execute the transformation and return flat action output dicts."""
