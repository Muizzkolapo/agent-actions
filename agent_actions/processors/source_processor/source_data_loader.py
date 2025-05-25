"""Module for loading source data."""
import os
from pathlib import Path
import json
from typing import List, Dict
from ..interfaces import ISourceDataLoader

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
        source_file_to_load = None  
        try:
            current_input_file_obj = Path(file_path)
            parts = current_input_file_obj.parts

            
            # Expected structure: .../PIPELINE_NAME_DIR/agent_io/target/NODE_NAME_DIR/rest/of/path.json
            agent_io_index = -1
            for i, part in enumerate(parts):
                if part == "agent_io":
                    agent_io_index = i
                    break
            
            if agent_io_index == -1:
                raise ValueError(f"Path structure error: 'agent_io' not found in {file_path}")
            if agent_io_index == 0 and parts[0] == "agent_io": # Check if agent_io is the first part of a relative path
                 raise ValueError(f"Path structure error: 'agent_io' cannot be the root of the path in {file_path}")
            if agent_io_index < 1 and parts[0] != '/': # Relative path starting with agent_io, needs a parent
                 raise ValueError(f"Path structure error: 'agent_io' needs a preceding PIPELINE_NAME_DIR in {file_path}")


            pipeline_name_dir = Path(*parts[:agent_io_index])

            if len(parts) <= agent_io_index + 2:
                raise ValueError(f"Path structure error: Path too short to contain NODE_NAME_DIR after 'agent_io/target/' in {file_path}")
            
            mirrored_structure_parts = parts[agent_io_index + 3:]
            relative_path_for_source = Path(*mirrored_structure_parts)
            
            source_file_to_load = pipeline_name_dir / "agent_io" / "source" / relative_path_for_source

            with open(source_file_to_load, 'r', encoding='utf-8') as file:
                return json.load(file)
        except Exception as e:
            raise IOError(f"Failed to load source data from {str(source_file_to_load)} (derived from input {file_path}): {str(e)}")

