"""Module for loading source data."""
import os
import json
from pathlib import Path
from typing import List, Dict, Optional

from .interfaces import ISourceDataLoader


class SourceDataLoader(ISourceDataLoader):
    """Handles loading source data (Single Responsibility)."""

    def __init__(self, agent_name: str):
        """
        Initialize the source data loader.
        
        Args:
            agent_name: Name of the agent
        """
        self.agent_name = agent_name

    def load_source_data(self, file_path: str) -> List[Dict]:
        """
        Load source data from the source directory.
        
        Args:
            file_path: Path to the file containing processed data
            
        Returns:
            List of source data items
            
        Raises:
            IOError: If source data cannot be loaded
        """
        try:
            source_path = Path(file_path).parents[2] / "source" / os.path.basename(file_path)
            with open(source_path, 'r') as file:
                return json.load(file)
        except Exception as e:
            raise IOError(f"Failed to load source data from {file_path}: {str(e)}")