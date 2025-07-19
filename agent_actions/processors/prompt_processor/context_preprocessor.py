"""Module for preprocessing context data."""
from agent_actions.processors.common.utils import apply_remove_collection


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
        return apply_remove_collection(context_data, agent_config)
    
    @staticmethod
    def extract_guid_and_content(context_data):
        """
        Extract source_guid and content from context data if available.
        
        Parameters:
            context_data: Data to extract from
            
        Returns:
            Tuple of (source_guid, content) where source_guid may be None
        """
        if isinstance(context_data, dict) and "source_guid" in context_data and "content" in context_data:
            return context_data["source_guid"], context_data["content"]
        return None, context_data