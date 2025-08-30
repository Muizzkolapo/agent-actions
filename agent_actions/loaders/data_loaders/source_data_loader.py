"""Module for loading source data."""
from pathlib import Path
import json
from typing import List, Dict, Any, Optional
from agent_actions.common.interfaces.interfaces import ISourceDataLoader, ProcessingMode
from ...core.path_manager import PathManager, PathManagerError
from ...core.dependency_injection import registry
from agent_actions.cli.exceptions import DependencyError

@registry.register_loader("source_data")
class SourceDataLoader(ISourceDataLoader):
    """Handles loading source data (Single Responsibility)."""

    def __init__(self, agent_name: str, path_manager: PathManager):
        """
        Initialize the source data loader.

        Args:
            agent_name: Name of the agent
            path_manager: Required PathManager instance for path operations (must be provided)
            
        Raises:
            DependencyError: If path_manager is not provided
        """
        self.agent_name = agent_name
        
        # Validate required dependency
        if path_manager is None:
            raise DependencyError("SourceDataLoader", "path_manager")
        
        self.path_manager = path_manager
    
    def supports_async(self) -> bool:
        """Return True as this loader supports async operations."""
        return True
    
    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode to let system choose."""
        return ProcessingMode.AUTO

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

            # Find agent_io/target structure
            try:
                agent_io_index = parts.index("agent_io")
                if len(parts) <= agent_io_index + 1 or parts[agent_io_index + 1] != "target":
                    raise ValueError
            except ValueError:
                raise PathManagerError(f"'agent_io' not found in path {file_path}")

            # Validate path structure has node directory and filename
            node_part = parts[agent_io_index + 2] if len(parts) > agent_io_index + 2 else None
            if node_part is None or Path(node_part).suffix:
                raise PathManagerError(
                    f"Path too short - missing node directory after 'agent_io/target/' in {file_path}"
                )
            file_parts = parts[agent_io_index + 3:]
            if not file_parts:
                raise PathManagerError(f"No filename found after node directory in {file_path}")

            # Extract parts: everything before agent_io + agent_io + source + everything after node directory
            pipeline_parts = parts[:agent_io_index]
            
            # Construct source path: .../agent_io/source/filename.json
            source_file_to_load = Path(*pipeline_parts) / "agent_io" / "source" / Path(*file_parts)
            
            # Ensure the source file exists and is readable
            if not source_file_to_load.exists():
                raise FileNotFoundError(f"Source file not found: {source_file_to_load}")
            
            # Validate the source file is within the project structure (if project root can be found)
            try:
                within_project = self.path_manager.is_within_project(source_file_to_load)
            except Exception:
                within_project = True
            if not within_project:
                raise ValueError(
                    f"Source file is outside project bounds: {source_file_to_load}"
                )
            
            with open(source_file_to_load, 'r', encoding='utf-8') as file:
                return json.load(file)
                
        except PathManagerError as e:
            raise IOError(f"Path structure error when deriving source from {file_path}: {e}")
        except Exception as e:
            raise IOError(f"Failed to load source data from {str(source_file_to_load)} (derived from input {file_path}): {str(e)}")

    def save_source_data(self, file_path: str, source_guid: str, content: Dict) -> None:
        """
        Save source data to the source directory.
        
        Args:
            file_path: Path to the file containing processed data
            source_guid: source_guid to associate with the content
            content: Content to save
        """
        # For now, implement as a pass-through or basic implementation
        # This method would need specific business logic based on requirements
        try:
            # Convert target path to source path similar to load_source_data
            target_path = self.path_manager.normalize_path(file_path)
            parts = target_path.parts
            
            # Find agent_io index
            try:
                agent_io_index = parts.index("agent_io")
            except ValueError:
                raise PathManagerError(f"'agent_io' not found in path {file_path}")
            
            # Construct source directory path
            pipeline_parts = parts[:agent_io_index]
            source_dir = Path(*pipeline_parts) / "agent_io" / "source"
            
            # Ensure source directory exists
            source_dir.mkdir(parents=True, exist_ok=True)
            
            # Create source file path with source_guid
            source_file = source_dir / f"{source_guid}.json"
            
            # Save content to source file
            with open(source_file, 'w', encoding='utf-8') as f:
                json.dump(content, f, indent=2)
                
        except Exception as e:
            raise IOError(f"Failed to save source data with guid {source_guid}: {str(e)}")

    def load_source_content(self, file_path: str, context_data: Dict[str, Any]) -> Optional[Any]:
        """
        Load specific content from source file by source_guid.
        
        Args:
            file_path: Path to the file containing processed data
            context_data: Context data containing source_guid
            
        Returns:
            Optional[Any]: Loaded content or None if not found
        """
        try:
            source_guid = context_data.get('source_guid')
            if not source_guid:
                return None
            
            # Load all source data and find the specific content
            source_data = self.load_source_data(file_path)
            
            # Find content by source_guid
            for item in source_data:
                if item.get('source_guid') == source_guid:
                    return item.get('content')
            
            return None
            
        except Exception as e:
            # Return None if content cannot be found/loaded
            return None

