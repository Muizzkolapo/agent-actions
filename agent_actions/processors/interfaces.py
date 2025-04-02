"""Common interfaces for processors."""
from typing import List, Dict, Optional, Any

class ISourceDataLoader:
    """Interface for source data loading operations."""
    
    def load_source_data(self, file_path: str) -> List[Dict]:
        """
        Load source data from the source directory.
        
        Args:
            file_path: Path to the file containing processed data
            
        Returns:
            List of source data items
        """
        pass
        
    def save_source_data(self, file_path: str, guid: str, content: Dict) -> None:
        """
        Save source data to the source directory.
        
        Args:
            file_path: Path to the file containing processed data
            guid: GUID to associate with the content
            content: Content to save
        """
        pass
        
    def load_source_content(self, file_path: str, context_data: Dict[str, Any]) -> Optional[Any]:
        """
        Load specific content from source file by GUID.
        
        Args:
            file_path: Path to the file containing processed data
            context_data: Context data containing GUID
            
        Returns:
            Optional[Any]: Loaded content or None if not found
        """
        pass 