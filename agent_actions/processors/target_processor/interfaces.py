"""Interfaces for target content processing."""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class IContentProcessor(ABC):
    """Interface for content processors."""

    @abstractmethod
    def process(self, data: List[Dict], file_path: str) -> List[Dict]:
        """Process a list of data items."""
        pass

    @abstractmethod
    def process_for_side_output(self, data: List[Dict], file_path: str) -> Tuple[List[Dict], List[Dict]]:
        """Process data and separate into main and side outputs."""
        pass


class IDataGenerator(ABC):
    """Interface for data generation."""

    @abstractmethod
    def create_agent_with_data(
        self, contents: Dict, source_content: Optional[Any] = None
    ) -> Tuple[List[Dict], bool]:
        """Create an agent with the provided data and return results."""
        pass


class IDataProcessor(ABC):
    """Interface for data processing."""

    @abstractmethod
    def process_item(self, contents: Dict, generated_data: List[Dict], guid: str) -> List[Dict]:
        """Process a single data item."""
        pass