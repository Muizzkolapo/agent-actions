"""Schema preparation service for agent builder."""

from typing import Dict, Any, Optional
from agent_actions.response_processing.schema_change import prepare_schema_unified


class SchemaService:
    """Handles schema preparation for agents."""

    @staticmethod
    def prepare_schema(agent_config: Dict[str, Any], model_vendor: str) -> Optional[Dict[str, Any]]:
        """
        Prepare schema for the given vendor.

        Uses the unified prepare_schema_unified() function to ensure consistent
        schema handling across online and batch modes.

        Args:
            agent_config: Agent configuration containing schema settings
            model_vendor: The model vendor (e.g., 'openai', 'anthropic')

        Returns:
            Prepared schema dict or None
        """
        return prepare_schema_unified(agent_config, model_vendor)
