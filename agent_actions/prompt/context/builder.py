"""Unified LLM context builder for batch and online modes."""

from typing import Any

from agent_actions.input.preprocessing.transformation.transformer import DataTransformer
from agent_actions.prompt.context.scope_parsing import parse_field_reference


class LLMContextBuilder:
    """
    Unified builder for LLM context across batch and online modes.

    This class provides a shared implementation for building LLM context,
    ensuring consistent merge and drop behavior regardless of processing mode.
    Both batch and online methods delegate to _build_llm_context to prevent
    behavioral drift and reduce code duplication.
    """

    @staticmethod
    def _build_llm_context(
        base_context: dict[str, Any],
        additional_context: dict[str, Any] | None,
        context_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Shared implementation for building LLM context.

        This method centralizes the merge and drop logic used by both batch
        and online modes. It performs the following operations in order:
        1. Creates a shallow copy of base_context to avoid mutating the original
        2. Merges additional_context fields (from context_scope.observe)
        3. Applies context_scope.drop rules to remove specified fields

        Args:
            base_context: Base context dict (row_content in batch, processed_context
                         in online). Must be a dict; caller should validate.
            additional_context: Fields to merge from context_scope.observe. Can be
                               None or empty dict if no additional fields.
            context_scope: Optional context scope configuration containing 'drop'
                          rules for field removal.

        Returns:
            New dict with merged fields and drops applied. Never mutates inputs.

        Note:
            Copy semantics: Only shallow copies are made of base_context and seed.
            Nested objects (other than seed) are shared references. Callers passing
            mutable nested structures should copy them first if mutation isolation
            is required.

            Behavioral note: Non-seed drops use DataTransformer.remove_schema_objects()
            which creates a new filtered dict. This differs from the original batch
            implementation that used dict.pop() but is semantically equivalent for
            return values.

            Invalid field references are silently skipped for backward compatibility.
        """
        # Create a copy to avoid mutating the original base_context
        result_context = base_context.copy() if isinstance(base_context, dict) else {}

        # Merge additional context fields (from context_scope.observe)
        if additional_context and isinstance(additional_context, dict):
            result_context.update(additional_context)

        # Apply drop rules from context_scope
        if context_scope and context_scope.get("drop"):
            seed_drop_fields = []
            drop_fields = []

            # Parse and categorize drop field references
            for field_ref in context_scope.get("drop", []):
                try:
                    action_name, field_name = parse_field_reference(field_ref)
                    if action_name == "seed":
                        seed_drop_fields.append(field_name)
                    else:
                        drop_fields.append(field_name)
                except ValueError:
                    # Invalid field reference - skip silently for backward compatibility
                    continue

            # Handle seed field drops with copy to prevent mutation of nested dicts
            if seed_drop_fields:
                seed_data = result_context.get("seed")
                if isinstance(seed_data, dict):
                    # Create a copy before modifying to avoid side effects
                    seed_data = seed_data.copy()
                    for field_name in seed_drop_fields:
                        seed_data.pop(field_name, None)
                    # Update or remove seed based on whether it's empty
                    if seed_data:
                        result_context["seed"] = seed_data
                    else:
                        result_context.pop("seed", None)

            # Handle non-seed drops via DataTransformer for consistency
            if drop_fields:
                result_context = DataTransformer.remove_schema_objects(result_context, drop_fields)

        return result_context

    @staticmethod
    def build_llm_context_for_batch(
        row_content: dict[str, Any],
        llm_context: dict[str, Any],
        context_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Build LLM context for batch mode.

        Delegates to the shared _build_llm_context implementation for consistent
        merge/drop behavior across modes.

        Args:
            row_content: Row content dict from batch processing. If not a dict,
                        returns empty dict.
            llm_context: Additional context fields from context_scope.observe.
            context_scope: Optional context scope with 'drop' rules.

        Returns:
            Dict with row_content as base, llm_context merged in, and drops applied.
        """
        # Validate base context type before delegation
        if not isinstance(row_content, dict):
            return {}  # type: ignore[unreachable]

        return LLMContextBuilder._build_llm_context(row_content, llm_context, context_scope)

    @staticmethod
    def build_llm_context_for_online(
        processed_context: dict[str, Any],
        llm_additional_context: dict[str, Any] | None,
        context_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Build LLM context for online mode.

        Delegates to the shared _build_llm_context implementation for consistent
        merge/drop behavior across modes.

        Args:
            processed_context: Processed context dict from online flow. If not
                              a dict, returns unchanged (passthrough behavior).
            llm_additional_context: Additional context from context_scope.observe.
            context_scope: Optional context scope with 'drop' rules.

        Returns:
            Dict with processed_context as base, additional context merged in,
            and drops applied. Returns input unchanged if not a dict.
        """
        # Preserve passthrough behavior for non-dict inputs
        if not isinstance(processed_context, dict):
            return processed_context  # type: ignore[unreachable]

        return LLMContextBuilder._build_llm_context(
            processed_context,
            llm_additional_context,
            context_scope,
        )
