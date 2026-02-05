"""Schema preparation service for agent builder."""

from typing import Dict, Any, Optional, Tuple
from agent_actions.output.response.schema import prepare_schema_unified


class SchemaService:
    """Handles schema preparation for agents.

    .. deprecated::
        TODO(v3.0): Remove -- callers should use prepare_schema_unified() directly.
    """

    @staticmethod
    def prepare_schema(
        agent_config: Dict[str, Any],
        model_vendor: str,
        tools_path: Optional[str] = None,
        context_data: Optional[Any] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """
        Prepare schema for the given vendor.

        Uses the unified prepare_schema_unified() function to ensure consistent
        schema handling across online and batch modes.

        Args:
            agent_config: Agent configuration containing schema settings
            model_vendor: The model vendor (e.g., 'openai', 'anthropic')
            tools_path: Path to tools directory (optional)
            context_data: Context data for dispatch functions (optional)

        Returns:
            Tuple containing:
            1. Prepared schema dict or None
            2. Captured results from dispatch_task
        """
        return prepare_schema_unified(agent_config, model_vendor, tools_path, context_data)
