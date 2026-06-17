"""Passthrough strategies for pre-computed passthrough_fields."""

import copy

from .base import IPassthroughTransformStrategy, ensure_dict_output


class PrecomputedStructuredStrategy(IPassthroughTransformStrategy):
    """Merge precomputed passthrough fields into structured data items."""

    def can_handle(
        self,
        data: list,
        passthrough_fields: dict | None,
        agent_config: dict,
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
        data: list,
        context_data: dict,
        source_guid: str,
        agent_config: dict,
        passthrough_fields: dict | None = None,
    ) -> list:
        """Merge passthrough fields into content, return flat action output.

        Returns flat action output dicts — RecordEnvelope handles wrapping.
        """
        pt = passthrough_fields or {}
        result = []
        for item in data:
            if isinstance(item, dict) and "content" in item and isinstance(item["content"], dict):
                result.append({**item["content"], **copy.deepcopy(pt)})
            elif isinstance(item, dict):
                result.append({**item, **copy.deepcopy(pt)})
            else:
                result.append(ensure_dict_output(item))
        return result


class PrecomputedUnstructuredStrategy(IPassthroughTransformStrategy):
    """Merge precomputed passthrough fields into unstructured data."""

    def can_handle(
        self,
        data: list,
        passthrough_fields: dict | None,
        agent_config: dict,
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
        data: list,
        context_data: dict,
        source_guid: str,
        agent_config: dict,
        passthrough_fields: dict | None = None,
    ) -> list:
        """Merge passthrough fields directly into items, return flat action output.

        Returns flat action output dicts — RecordEnvelope handles wrapping.
        """
        pt = passthrough_fields or {}
        merged = []
        for item in data:
            if isinstance(item, dict):
                merged.append({**item, **copy.deepcopy(pt)})
            else:
                merged.append(ensure_dict_output(item))
        return merged
