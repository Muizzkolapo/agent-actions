"""Passthrough strategies for pre-computed passthrough_fields.

These strategies only normalize items to flat action output dicts. The
namespaced passthrough_fields themselves are merged at content level by
``PassthroughTransformer`` — never into the action output, which would nest
the passthrough namespace inside the action's own namespace.
"""

from .base import IPassthroughTransformStrategy, ensure_dict_output


class PrecomputedStructuredStrategy(IPassthroughTransformStrategy):
    """Normalize structured data items when precomputed passthrough fields exist."""

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
        """Unwrap item content, returning flat action output dicts."""
        result = []
        for item in data:
            if isinstance(item, dict) and "content" in item and isinstance(item["content"], dict):
                result.append(dict(item["content"]))
            elif isinstance(item, dict):
                result.append(dict(item))
            else:
                result.append(ensure_dict_output(item))
        return result


class PrecomputedUnstructuredStrategy(IPassthroughTransformStrategy):
    """Normalize unstructured data items when precomputed passthrough fields exist."""

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
        """Return items as flat action output dicts."""
        merged = []
        for item in data:
            if isinstance(item, dict):
                merged.append(dict(item))
            else:
                merged.append(ensure_dict_output(item))
        return merged
