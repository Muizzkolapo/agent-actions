"""Common interfaces for processors."""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any, Tuple


# Base interfaces
class ILoader(ABC):
    """Base interface for all loaders."""
    pass


class IProcessor(ABC):
    """Base interface for all processors."""
    pass


class IGenerator(ABC):
    """Base interface for all generators."""
    pass


# Loader interfaces
class IDataLoader(ILoader):
    """Interface for data loading operations."""
    
    def load_data(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Loads data from the given file path.

        Args:
            file_path: The path to the data file.

        Returns:
            A list of dictionaries, where each dictionary represents a row of data.
        """
        pass


class ISourceDataLoader(ILoader):
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
        
    def save_source_data(self, file_path: str, source_guid: str, content: Dict) -> None:
        """
        Save source data to the source directory.
        
        Args:
            file_path: Path to the file containing processed data
            source_guid: source_guid to associate with the content
            content: Content to save
        """
        pass
        
    def load_source_content(self, file_path: str, context_data: Dict[str, Any]) -> Optional[Any]:
        """
        Load specific content from source file by source_guid.
        
        Args:
            file_path: Path to the file containing processed data
            context_data: Context data containing source_guid
            
        Returns:
            Optional[Any]: Loaded content or None if not found
        """
        pass


# Processor interfaces
class IContentProcessor(IProcessor):
    """Interface for content processors."""

    @abstractmethod
    def process(self, data: List[Dict], file_path: str) -> List[Dict]:
        """Process a list of data items."""
        pass

    @abstractmethod
    def process_for_side_output(self, data: List[Dict], file_path: str) -> Tuple[List[Dict], List[Dict]]:
        """Process data and separate into main and side outputs."""
        pass


class IDataProcessor(IProcessor):
    """Interface for data processing."""

    @abstractmethod
    def process_item(self, contents: Dict, generated_data: List[Dict], source_guid: str) -> List[Dict]:
        """Process a single data item."""
        pass


# Generator interfaces
class IDataGenerator(IGenerator):
    """Interface for data generation."""

    @abstractmethod
    def create_agent_with_data(
        self, contents: Dict, source_content: Optional[Any] = None
    ) -> Tuple[List[Dict], bool]:
        """Create an agent with the provided data and return results."""
        pass 