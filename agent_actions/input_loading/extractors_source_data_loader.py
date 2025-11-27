"""Module for loading source data."""
from pathlib import Path
import json
import logging
from typing import List, Dict, Any, Optional
from agent_actions.configuration.interfaces import ISourceDataLoader, ProcessingMode
from agent_actions.state_management.path_manager import PathManager, PathManagerError
from agent_actions.orchestration.dependency_injection import registry
from agent_actions.shared.exceptions import DependencyError

logger = logging.getLogger(__name__)

@registry.register_loader('source_data')
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
        if path_manager is None:
            raise DependencyError('SourceDataLoader', 'path_manager')
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
            target_path = self.path_manager.normalize_path(file_path)
            parts = target_path.parts
            try:
                agent_io_index = parts.index('agent_io')
                if len(parts) <= agent_io_index + 1 or parts[agent_io_index + 1] != 'target':
                    raise ValueError
            except ValueError:
                raise PathManagerError(f"'agent_io' not found in path {file_path}")
            node_part = parts[agent_io_index + 2] if len(parts) > agent_io_index + 2 else None
            if node_part is None or Path(node_part).suffix:
                from agent_actions.shared.exceptions import FileSystemError
                raise FileSystemError("Path too short - missing node directory after 'agent_io/target/'", context={'file_path': file_path, 'agent_name': self.agent_name, 'operation': 'load_source_data'})
            file_parts = parts[agent_io_index + 3:]
            if not file_parts:
                from agent_actions.shared.exceptions import FileSystemError
                raise FileSystemError('No filename found after node directory', context={'file_path': file_path, 'agent_name': self.agent_name, 'operation': 'load_source_data'})
            pipeline_parts = parts[:agent_io_index]
            source_file_to_load = Path(*pipeline_parts) / 'agent_io' / 'source' / Path(*file_parts)
            if not source_file_to_load.exists():
                raise FileNotFoundError(f'Source file not found: {source_file_to_load}')
            try:
                within_project = self.path_manager.is_within_project(source_file_to_load)
            except Exception as e:
                logger.debug(
                    "Could not verify if source file is within project bounds, assuming valid: %s",
                    e,
                    extra={
                        'source_file': str(source_file_to_load),
                        'agent_name': self.agent_name,
                        'operation': 'path_validation'
                    }
                )
                within_project = True
            if not within_project:
                from agent_actions.shared.exceptions import FileSystemError
                raise FileSystemError('Source file is outside project bounds', context={'source_file': str(source_file_to_load), 'agent_name': self.agent_name, 'operation': 'load_source_data'})
            with open(source_file_to_load, 'r', encoding='utf-8') as file:
                return json.load(file)
        except PathManagerError as e:
            from agent_actions.shared.exceptions import FileSystemError
            raise FileSystemError('Path structure error when deriving source', context={'file_path': file_path, 'agent_name': self.agent_name, 'operation': 'load_source_data'}, cause=e)
        except Exception as e:
            from agent_actions.shared.exceptions import FileLoadError
            raise FileLoadError(
                'Failed to load source data',
                context={
                    'source_file': str(source_file_to_load) if source_file_to_load else 'unknown',
                    'input_file_path': file_path,
                    'agent_name': self.agent_name,
                    'operation': 'load_source_data',
                    'suggestion': 'Check if the source file exists and has valid JSON/YAML format. Verify file permissions.'
                },
                cause=e
            )

    def save_source_data(self, file_path: str, source_guid: str, content: Dict) -> None:
        """
        Save source data to the source directory.
        
        Args:
            file_path: Path to the file containing processed data
            source_guid: source_guid to associate with the content
            content: Content to save
        """
        try:
            target_path = self.path_manager.normalize_path(file_path)
            parts = target_path.parts
            try:
                agent_io_index = parts.index('agent_io')
            except ValueError:
                raise PathManagerError(f"'agent_io' not found in path {file_path}")
            pipeline_parts = parts[:agent_io_index]
            source_dir = Path(*pipeline_parts) / 'agent_io' / 'source'
            source_dir.mkdir(parents=True, exist_ok=True)
            source_file = source_dir / f'{source_guid}.json'
            with open(source_file, 'w', encoding='utf-8') as f:
                json.dump(content, f, indent=2)
        except Exception as e:
            from agent_actions.shared.exceptions import FileLoadError
            raise FileLoadError('Failed to save source data', context={'source_guid': source_guid, 'file_path': file_path, 'agent_name': self.agent_name, 'operation': 'save_source_data'}, cause=e)

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
            source_data = self.load_source_data(file_path)
            for item in source_data:
                if item.get('source_guid') == source_guid:
                    return item.get('content')
            return None
        except Exception as e:
            logger.warning(
                "Failed to load source content for source_guid %s from %s: %s",
                context_data.get('source_guid'), file_path, e,
                exc_info=True,
                extra={
                    'source_guid': context_data.get('source_guid'),
                    'file_path': file_path,
                    'agent_name': self.agent_name,
                    'operation': 'load_source_content'
                }
            )
            return None