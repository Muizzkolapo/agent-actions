"""Passthrough strategies for pre-computed passthrough_fields."""

from typing import Dict, List, Optional

from agent_actions.input.preprocessing.transformation.transformer import DataTransformer
from .base import IPassthroughTransformStrategy


class PrecomputedStructuredStrategy(IPassthroughTransformStrategy):
    """Merge precomputed passthrough fields into structured data items."""

    def can_handle(
        self,
        data: List,
        passthrough_fields: Optional[Dict],
        agent_config: Dict,
        already_structured: bool,
    ) -> bool:
        """Check if we have precomputed fields and structured data."""
        return (
            passthrough_fields is not None
            and isinstance(passthrough_fields, dict)
            and len(passthrough_fields) > 0
            and already_structured
        )

    def transform(
        self,
        data: List,
        context_data: Dict,
        source_guid: str,
        agent_config: Dict,
        passthrough_fields: Optional[Dict] = None,
    ) -> List:
        """Merge passthrough fields into each item's content."""
        result = []
        for item in data:
            if isinstance(item, dict) and "content" in item and isinstance(item["content"], dict):
                merged = {**item, "content": {**item["content"], **passthrough_fields}}
                result.append(merged)
            else:
                result.append(item)
        return result


class PrecomputedUnstructuredStrategy(IPassthroughTransformStrategy):
    """Merge precomputed passthrough fields into unstructured data, then structure."""

    def can_handle(
        self,
        data: List,
        passthrough_fields: Optional[Dict],
        agent_config: Dict,
        already_structured: bool,
    ) -> bool:
        """Check if we have precomputed fields and unstructured data."""
        return (
            passthrough_fields is not None
            and isinstance(passthrough_fields, dict)
            and len(passthrough_fields) > 0
            and not already_structured
        )

    def transform(
        self,
        data: List,
        context_data: Dict,
        source_guid: str,
        agent_config: Dict,
        passthrough_fields: Optional[Dict] = None,
    ) -> List:
        """Merge passthrough fields directly into items."""
        merged = []
        for item in data:
            if isinstance(item, dict):
                merged_item = {**item, **passthrough_fields}
                merged.append(merged_item)
            else:
                merged.append(item)
        return DataTransformer.transform_structure([{source_guid: merged}])
