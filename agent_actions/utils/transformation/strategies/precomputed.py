"""Passthrough strategies for pre-computed passthrough_fields."""

from .base import IPassthroughTransformStrategy


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
        result = []
        for item in data:
            if isinstance(item, dict) and "content" in item and isinstance(item["content"], dict):
                merged_content = {**item["content"], **(passthrough_fields or {})}
                result.append(merged_content)
            elif isinstance(item, dict):
                result.append({**item, **(passthrough_fields or {})})
            else:
                result.append(item)
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
        merged = []
        for item in data:
            if isinstance(item, dict):
                merged_item = {**item, **(passthrough_fields or {})}
                merged.append(merged_item)
            else:
                merged.append(item)
        return merged
