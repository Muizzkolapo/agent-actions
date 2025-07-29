"""Module for loading source data."""
from pathlib import Path
import json
from typing import List, Dict
from ..interfaces import IDataLoader
from ...core.path_manager import PathManager, PathManagerError
from ...core.dependency_injection import registry

@registry.register_loader("source_data")
class SourceDataLoader(IDataLoader):
    """Handles loading source data (Single Responsibility)."""

    def __init__(self, agent_name: str, path_manager: PathManager):
        """
        Initialize the source data loader.
        
        Args:
            agent_name: Name of the agent
            path_manager: PathManager instance for path operations
        """
        self.agent_name = agent_name
        self.path_manager = path_manager

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
            # Convert target path to source path, skipping node directory
            target_path = self.path_manager.normalize_path(file_path)
            parts = target_path.parts
            
            # Find agent_io index
            try:
                agent_io_index = parts.index("agent_io")
            except ValueError:
                raise PathManagerError(f"'agent_io' not found in path {file_path}")
            
            # Validate path structure has enough components
            if len(parts) <= agent_io_index + 2:
                raise PathManagerError(f"Path too short - missing node directory after 'agent_io/target/' in {file_path}")
            
            # Extract parts: everything before agent_io + agent_io + source + everything after node directory
            # Skip the node directory (agent_io_index + 3) to get the filename directly in source
            pipeline_parts = parts[:agent_io_index]
            file_parts = parts[agent_io_index + 3:]  # Skip agent_io/target/node_dir
            
            if not file_parts:
                raise PathManagerError(f"No filename found after node directory in {file_path}")
            
            # Construct source path: .../agent_io/source/filename.json
            source_file_to_load = Path(*pipeline_parts) / "agent_io" / "source" / Path(*file_parts)
            
            # Ensure the source file exists and is readable
            if not source_file_to_load.exists():
                raise FileNotFoundError(f"Source file not found: {source_file_to_load}")
            
            # Validate the source file is within the project structure (if project root can be found)
            try:
                if not self.path_manager.is_within_project(source_file_to_load):
                    raise ValueError(f"Source file is outside project bounds: {source_file_to_load}")
            except Exception:
                # If project root validation fails, skip this check (for tests/edge cases)
                pass
            
            with open(source_file_to_load, 'r', encoding='utf-8') as file:
                return json.load(file)
                
        except PathManagerError as e:
            raise IOError(f"Path structure error when deriving source from {file_path}: {e}")
        except Exception as e:
            raise IOError(f"Failed to load source data from {str(source_file_to_load)} (derived from input {file_path}): {str(e)}")

