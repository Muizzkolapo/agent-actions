"""Passthrough strategies that extract fields from context_scope.passthrough config."""

from agent_actions.input.preprocessing.transformation.transformer import DataTransformer

from .base import IPassthroughTransformStrategy, ensure_dict_output


class ContextScopeStructuredStrategy(IPassthroughTransformStrategy):
    """Handle context_scope passthrough with structured data."""

    def can_handle(
        self,
        data: list,
        passthrough_fields: dict | None,
        agent_config: dict,
        already_structured: bool,
    ) -> bool:
        """Check if we have no precomputed fields, structured data."""
        has_passthrough_config = self.has_passthrough_config(agent_config)
        return (
            (passthrough_fields is None or len(passthrough_fields) == 0)
            and already_structured
            and has_passthrough_config
        )

    def transform(
        self,
        data: list,
        context_data: dict,
        source_guid: str,
        agent_config: dict,
        passthrough_fields: dict | None = None,
    ) -> list:
        """Extract and merge context_scope passthrough fields.

        Returns flat action output dicts — RecordEnvelope handles wrapping.
        """
        fields_to_merge = self.extract_context_scope_fields(agent_config)

        context_for_passthrough = context_data
        if (
            isinstance(context_data, dict)
            and "content" in context_data
            and isinstance(context_data["content"], dict)
        ):
            context_for_passthrough = context_data["content"]

        contents = [item["content"] for item in data]
        updated = []
        for content in contents:
            if isinstance(content, dict):
                updated.append(
                    DataTransformer.update_schema_objects(
                        context_for_passthrough, content, fields_to_merge
                    )
                )
            else:
                content_dict = {"content": content}
                updated.append(
                    DataTransformer.update_schema_objects(
                        context_for_passthrough, content_dict, fields_to_merge
                    )
                )
        return updated

    @staticmethod
    def has_passthrough_config(agent_config: dict) -> bool:
        """Check if agent_config has passthrough configuration."""
        context_scope = agent_config.get("context_scope", {})
        return bool(context_scope and context_scope.get("passthrough"))

    @staticmethod
    def extract_context_scope_fields(agent_config: dict) -> list[str]:
        """Extract field names from context_scope.passthrough."""
        from agent_actions.prompt.context.scope_parsing import extract_field_names_from_references

        context_scope = agent_config.get("context_scope", {})

        if context_scope and context_scope.get("passthrough"):
            passthrough_refs = context_scope.get("passthrough", [])
            return extract_field_names_from_references(passthrough_refs)

        return []


class ContextScopeUnstructuredStrategy(IPassthroughTransformStrategy):
    """Handle context_scope passthrough with unstructured data."""

    def can_handle(
        self,
        data: list,
        passthrough_fields: dict | None,
        agent_config: dict,
        already_structured: bool,
    ) -> bool:
        """Check if we have no precomputed fields, unstructured data."""
        has_passthrough_config = ContextScopeStructuredStrategy.has_passthrough_config(agent_config)
        return (
            (passthrough_fields is None or len(passthrough_fields) == 0)
            and not already_structured
            and has_passthrough_config
        )

    def transform(
        self,
        data: list,
        context_data: dict,
        source_guid: str,
        agent_config: dict,
        passthrough_fields: dict | None = None,
    ) -> list:
        """Extract and merge context_scope passthrough fields.

        Returns flat action output dicts — RecordEnvelope handles wrapping.
        """
        fields_to_merge = ContextScopeStructuredStrategy.extract_context_scope_fields(agent_config)

        context_for_passthrough = context_data
        if (
            isinstance(context_data, dict)
            and "content" in context_data
            and isinstance(context_data["content"], dict)
        ):
            context_for_passthrough = context_data["content"]

        updated = []
        for item in data:
            if isinstance(item, dict):
                updated.append(
                    DataTransformer.update_schema_objects(
                        context_for_passthrough, item, fields_to_merge
                    )
                )
            else:
                item_dict = {"content": item}
                updated.append(
                    DataTransformer.update_schema_objects(
                        context_for_passthrough, item_dict, fields_to_merge
                    )
                )
        return updated


class NoOpStrategy(IPassthroughTransformStrategy):
    """No-op strategy: extracts content from structured data when no passthrough is needed."""

    def can_handle(
        self,
        data: list,
        passthrough_fields: dict | None,
        agent_config: dict,
        already_structured: bool,
    ) -> bool:
        """Check if structured data with no passthrough."""
        has_passthrough_config = ContextScopeStructuredStrategy.has_passthrough_config(agent_config)
        return (
            already_structured
            and not has_passthrough_config
            and (passthrough_fields is None or len(passthrough_fields) == 0)
        )

    def transform(
        self,
        data: list,
        context_data: dict,
        source_guid: str,
        agent_config: dict,
        passthrough_fields: dict | None = None,
    ) -> list:
        """Extract content from structured items, return flat action output.

        Returns flat action output dicts — RecordEnvelope handles wrapping.
        """
        results = []
        for item in data:
            if isinstance(item, dict) and "content" in item:
                results.append(ensure_dict_output(item["content"]))
            else:
                results.append(ensure_dict_output(item))
        return results


class DefaultStructureStrategy(IPassthroughTransformStrategy):
    """Default strategy: returns unstructured data as flat action output dicts."""

    def can_handle(
        self,
        data: list,
        passthrough_fields: dict | None,
        agent_config: dict,
        already_structured: bool,
    ) -> bool:
        """Fallback catch-all: always returns True."""
        return True  # Catch-all

    def transform(
        self,
        data: list,
        context_data: dict,
        source_guid: str,
        agent_config: dict,
        passthrough_fields: dict | None = None,
    ) -> list:
        """Return data as flat action output dicts.

        Returns flat action output dicts — RecordEnvelope handles wrapping.
        """
        return [ensure_dict_output(item) for item in data]
