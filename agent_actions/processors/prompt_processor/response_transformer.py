"""Module for transforming agent responses."""
from agent_actions.transformers.data_transformer import DataTransformer
from agent_actions.constants import SIDE_COLLECTION_KEY


class ResponseTransformer:
    """Handles response transformation (Single Responsibility)."""
    
    @staticmethod
    def transform_response(response, context_data, guid, agent_config):
        """
        Transform agent response with context data.
        
        Parameters:
            response: Raw agent response data
            context_data: Original context data for side collections
            guid: Identifier for the response
            agent_config: Configuration containing transformation settings
            
        Returns:
            Transformed response structure
        """
        return transform_with_side_collection(
            response,
            context_data,
            guid,
            agent_config,
        )
