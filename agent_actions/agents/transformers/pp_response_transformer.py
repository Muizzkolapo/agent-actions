"""Module for transforming agent responses."""
from agent_actions.core.utils.processor_helpers import transform_with_observe


class ResponseTransformer:
    """Handles response transformation (Single Responsibility)."""
    
    @staticmethod
    def transform_response(response, context_data, source_guid, agent_config):
        """
        Transform agent response with context data.
        
        Parameters:
            response: Raw agent response data
            context_data: Original context data for side collections
            source_guid: Identifier for the response
            agent_config: Configuration containing transformation settings
            
        Returns:
            Transformed response structure
        """
        return transform_with_observe(
            response,
            context_data,
            source_guid,
            agent_config,
        )
