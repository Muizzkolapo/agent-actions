"""Module for preprocessing context data."""
from agent_actions.transformers.data_transformer import DataTransformer


class ContextPreprocessor:
    """Handles context data preprocessing (Single Responsibility)."""
    
    @staticmethod
    def prepare_context(context_data, agent_config):
        """
        Remove schema objects from context data if configured.
        
        Parameters:
            context_data: Data to process
            agent_config: Configuration containing transformation settings
            
        Returns:
            Processed context data
        """
        remove_collection = agent_config.get('remove_collection', [])
        if remove_collection and isinstance(context_data, dict):
            return DataTransformer.remove_schema_objects(context_data, remove_collection)
        return context_data
    
    @staticmethod
    def extract_guid_and_content(context_data):
        """
        Extract guid and content from context data if available.
        
        Parameters:
            context_data: Data to extract from
            
        Returns:
            Tuple of (guid, content) where guid may be None
        """
        if isinstance(context_data, dict) and "guid" in context_data and "content" in context_data:
            return context_data["guid"], context_data["content"]
        return None, context_data