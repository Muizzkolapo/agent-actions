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
        side_collection = agent_config.get(SIDE_COLLECTION_KEY, [])
        
        if side_collection:
            updated_response = [
                DataTransformer.update_schema_objects(context_data, data, side_collection)
                for data in response
            ]
            return DataTransformer.transform_structure([{guid: updated_response}])
        else:
            return DataTransformer.transform_structure([{guid: response}])