"""Module for transforming agent responses."""
from agent_actions.common.transformers.data_transformer import DataTransformer
from agent_actions.constants import SIDE_COLLECTION_KEY
from agent_actions.common.utils.utils import transform_with_side_collection


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
        return transform_with_side_collection(
            response,
            context_data,
            source_guid,
            agent_config,
        )
