"""Unified LLM context builder for batch and online modes."""

from typing import Any

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

        Merges namespaced additional_context (from context_scope.observe) into
        base_context and applies seed drop rules. Non-seed drops are already
        enforced upstream by apply_context_scope.

        Args:
            base_context: Base context dict. Must be a dict; caller should validate.
            additional_context: Namespaced fields from context_scope.observe:
                               {action_name: {field: value, ...}, ...}.
            context_scope: Optional context scope configuration containing 'drop'
                          rules for seed field removal.

        Returns:
            New dict with merged fields and seed drops applied. Never mutates inputs.
        """
        # Create a copy to avoid mutating the original base_context
        result_context = base_context.copy() if isinstance(base_context, dict) else {}

        # Merge additional context fields (from context_scope.observe)
        if additional_context and isinstance(additional_context, dict):
            result_context.update(additional_context)

        # Apply seed drop rules from context_scope.
        # Non-seed drops are already enforced upstream by apply_context_scope
        # (which removes dropped fields from prompt_context before observe extracts them).
        if context_scope and context_scope.get("drop"):
            seed_drop_fields = []

            for field_ref in context_scope.get("drop", []):
                try:
                    action_name, field_name = parse_field_reference(field_ref)
                    if action_name == "seed":
                        seed_drop_fields.append(field_name)
                except ValueError:
                    continue

            if seed_drop_fields:
                seed_data = result_context.get("seed")
                if isinstance(seed_data, dict):
                    seed_data = seed_data.copy()
                    for field_name in seed_drop_fields:
                        seed_data.pop(field_name, None)
                    if seed_data:
                        result_context["seed"] = seed_data
                    else:
                        result_context.pop("seed", None)

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
