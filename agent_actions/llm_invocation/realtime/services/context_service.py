"""Context preparation service for agent builder."""

import json
from typing import Dict, Any, Optional, Union


class ContextService:
    """Handles context preparation and transformation for agents."""

    @staticmethod
    def build_field_context(
        context_data: Union[str, Dict],
        agent_config: Dict[str, Any]
    ) -> Optional[Dict]:
        """
        Build field_context dict from context_data for field reference replacement.

        In agent_builder, we don't have the full dependency graph like DataGenerator,
        but we can build a basic field_context from available data.

        Args:
            context_data: The context data (str or dict)
            agent_config: Agent configuration (currently unused but kept for future use)

        Returns:
            field_context dict or None

        Example:
            Input: context_data = '{"page_content": "Hello", "title": "Test"}'
            Output: {'source': {'page_content': 'Hello', 'title': 'Test'}}
        """
        if isinstance(context_data, str):
            try:
                parsed = json.loads(context_data)
            except (json.JSONDecodeError, TypeError):
                return None
        elif isinstance(context_data, dict):
            parsed = context_data
        else:
            return None

        return {'source': parsed}

    @staticmethod
    def prepare_context_data(
        context_data_str: Union[str, Dict],
        original_context: Optional[Union[str, Dict]],
        is_tool: bool
    ) -> Union[str, Dict]:
        """
        Prepare context data for LLM/tool invocation.

        CRITICAL: For tool actions, use original_context (not transformed llm_data).
        Tools need access to ALL fields from previous actions, even those dropped
        by context_scope.drop for the LLM.

        Args:
            context_data_str: Context data for LLM (may have context_scope.drop applied)
            original_context: Original untransformed context for tools (optional)
            is_tool: Whether this is a tool vendor invocation

        Returns:
            Prepared context data (str or dict depending on vendor needs)
        """
        # CRITICAL FIX (Issue #487 - Phase 2):
        # For tool actions, use original_context (not transformed llm_data)
        if is_tool and original_context is not None:
            return original_context

        # For tool vendor, return context as-is (dict or str)
        # For LLM vendors, convert to JSON string if dict
        if is_tool:
            return context_data_str
        else:
            if isinstance(context_data_str, str):
                return context_data_str
            else:
                return json.dumps(context_data_str, ensure_ascii=False)

    @staticmethod
    def prepare_tool_context(
        context_data_str: Union[str, Dict],
        original_context: Optional[Union[str, Dict]]
    ) -> str:
        """
        Prepare tool context as JSON string for tool injection.

        CRITICAL: Use original_context for tool injection (has all fields from previous actions).
        Use context_data (transformed) for LLM only.

        Args:
            context_data_str: Transformed context data (with context_scope.drop applied)
            original_context: Original untransformed context for tools (optional)

        Returns:
            JSON string of tool context
        """
        # Use original context if available, otherwise use context_data_str
        tool_context = original_context if original_context is not None else context_data_str

        # Convert to JSON string if needed
        if isinstance(tool_context, str):
            return tool_context
        else:
            return json.dumps(tool_context, ensure_ascii=False)
