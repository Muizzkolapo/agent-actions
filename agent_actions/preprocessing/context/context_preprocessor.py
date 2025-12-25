"""Module for preprocessing context data."""

class ContextPreprocessor:
    """Handles context data preprocessing (Single Responsibility)."""

    def __repr__(self):
        """Return string representation of ContextPreprocessor."""
        return f"{self.__class__.__name__}()"

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
                    excluded_keys = [
                        'source_guid', 'target_id', 'record_index', 'chunk_index'
                    ]
                    content_data = {
                        k: v for k, v in value.items() if k not in excluded_keys
                    }
                    return (value['source_guid'], content_data)
        return (None, context_data)
