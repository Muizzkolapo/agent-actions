"""
Precomputed Passthrough Strategies.

These strategies handle transformation when passthrough_fields
are pre-computed and provided directly (new behavior).
"""
from typing import Dict, List, Optional

from agent_actions.preprocessing.transformation.data_transformer import DataTransformer
from .base import IPassthroughTransformStrategy


class PrecomputedStructuredStrategy(IPassthroughTransformStrategy):
    """
    Handle precomputed passthrough fields with structured data.

    Structured data format: [{'source_guid': ..., 'content': {...}}]
    Merges passthrough fields into each item's 'content' dict.
    """

    def can_handle(
        self,
        data: List,
        passthrough_fields: Optional[Dict],
        agent_config: Dict,
        already_structured: bool
    ) -> bool:
        """Check if we have precomputed fields and structured data."""
        return (
            passthrough_fields is not None
            and isinstance(passthrough_fields, dict)
            and len(passthrough_fields) > 0
            and already_structured
        )

    def transform(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        data: List,
        context_data: Dict,
        source_guid: str,
        agent_config: Dict,
        passthrough_fields: Optional[Dict] = None
    ) -> List:
        """Merge passthrough fields into each item's content."""
        for item in data:
            if (
                isinstance(item, dict)
                and 'content' in item
                and isinstance(item['content'], dict)
            ):
                item['content'].update(passthrough_fields)
        return data


class PrecomputedUnstructuredStrategy(IPassthroughTransformStrategy):
    """
    Handle precomputed passthrough fields with unstructured data.

    Unstructured data format: [{...}, {...}] (plain dicts or mixed)
    Merges passthrough fields directly into items, then structures.
    """

    def can_handle(
        self,
        data: List,
        passthrough_fields: Optional[Dict],
        agent_config: Dict,
        already_structured: bool
    ) -> bool:
        """Check if we have precomputed fields and unstructured data."""
        return (
            passthrough_fields is not None
            and isinstance(passthrough_fields, dict)
            and len(passthrough_fields) > 0
            and not already_structured
        )

    def transform(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        data: List,
        context_data: Dict,
        source_guid: str,
        agent_config: Dict,
        passthrough_fields: Optional[Dict] = None
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
