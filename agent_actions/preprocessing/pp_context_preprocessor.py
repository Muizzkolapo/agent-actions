"""Module for preprocessing context data."""
from agent_actions.utilities.utils_processor_helpers import apply_drops

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
        return apply_drops(context_data, agent_config)

    @staticmethod
    def extract_guid_and_content(context_data):
        """
        Extract source_guid and content from context data if available.
        Handles nested chunked record format: {"uuid": {"source_guid": "...", ...}}
        
        Parameters:
            context_data: Data to extract from
            
        Returns:
            Tuple of (source_guid, content) where source_guid may be None
        """
        if isinstance(context_data, dict):
            for _, value in context_data.items():
                if isinstance(value, dict) and 'source_guid' in value:
                    content_data = {k: v for k, v in value.items() if k not in ['source_guid', 'target_id', 'record_index', 'chunk_index']}
                    return (value['source_guid'], content_data)
        return (None, context_data)