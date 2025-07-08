"""Module for managing source paths and files."""
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union
from agent_actions.cli.utils.service_logger import ServiceLogger

logger = logging.getLogger(__name__)

class SourcePathManager:
    """Manages source paths and file operations (Single Responsibility Principle)."""
    
    @staticmethod
    def get_source_path(file_path: str) -> Path:
        """
        Get the source path for a given file path.
        
        Args:
            file_path: Path to the original file
            
        Returns:
            Path: Path to the source file
        """
        try:
            ServiceLogger.log_operation_start(logger, "get source path", file_path=file_path)
            
            file_path = Path(file_path)
            agent_dir = file_path.parents[1]  # Go up two levels to get agent directory
            source_dir = agent_dir / "source"
            source_path = source_dir / file_path.name
            
            ServiceLogger.log_operation_success(logger, "get source path", 
                                             source_path=str(source_path))
            return source_path
            
        except Exception as e:
            ServiceLogger.log_operation_error(logger, "get source path", e)
            raise
            
    @staticmethod
    def ensure_source_directory(source_path: Union[str, Path]) -> None:
        """
        Ensure the source directory exists.
        
        Args:
            source_path: Path to the source file (can be string or Path object)
        """
        try:
            ServiceLogger.log_operation_start(logger, "ensure source directory", 
                                           source_path=str(source_path))
            
            # Convert string to Path if necessary
            if isinstance(source_path, str):
                source_path = Path(source_path)
                
            source_path.parent.mkdir(parents=True, exist_ok=True)
            
            ServiceLogger.log_operation_success(logger, "ensure source directory")
            
        except Exception as e:
            ServiceLogger.log_operation_error(logger, "ensure source directory", e)
            raise
            
    @staticmethod
    def load_source_content(
        source_path: Union[str, Path],
        context_data: Dict[str, Any]
    ) -> Optional[Any]:
        """
        Load source content based on the input documentation's GUID.
        If the source file doesn't exist, create it with an empty structure.
        
        Parameters:
            source_path: Path to the source file
            context_data: Context data containing GUID
            
        Returns:
            Loaded source content or empty structure if newly created
            
        Raises:
            IOError: If source content loading or creation fails
        """
        try:
            if not source_path:
                return None
                
            source_path = Path(source_path)
            # Create directory if it doesn't exist
            source_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Create empty source file if it doesn't exist
            if not source_path.exists():
                empty_source = []
                with open(source_path, 'w') as file:
                    json.dump(empty_source, file, indent=2)
                return None
                
            with open(source_path, 'r') as file:
                source_data = json.load(file)
                if isinstance(context_data, dict) and "guid" in context_data:
                    guid = context_data["guid"]
                    for item in source_data:
                        if guid in item:
                            return item[guid]
            return None
        except Exception as e:
            raise IOError(f"Failed to load or create source content: {str(e)}")
            
    @staticmethod
    def save_source_content(source_path: Path, guid: str, content: Any) -> None:
        """
        Save content to source file.
        
        Args:
            source_path: Path to the source file
            guid: GUID to associate with the content
            content: Content to save
        """
        try:
            ServiceLogger.log_operation_start(logger, "save source content", 
                                           source_path=str(source_path), guid=guid)
            
            # Ensure source directory exists
            SourcePathManager.ensure_source_directory(source_path)
            
            # Load existing content or create new list
            if source_path.exists():
                with open(source_path, 'r') as file:
                    source_data = json.load(file)
            else:
                source_data = []
                
            # Update or append content
            content_entry = {guid: content}
            updated = False
            for i, item in enumerate(source_data):
                if guid in item:
                    source_data[i] = content_entry
                    updated = True
                    break
                    
            if not updated:
                source_data.append(content_entry)
                
            # Save updated content
            with open(source_path, 'w') as file:
                json.dump(source_data, file, indent=2)
                
            ServiceLogger.log_operation_success(logger, "save source content", 
                                             guid=guid)
            
        except Exception as e:
            ServiceLogger.log_operation_error(logger, "save source content", e)
            raise 