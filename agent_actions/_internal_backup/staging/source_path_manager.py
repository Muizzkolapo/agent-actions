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
        Load source content based on the input documentation's source_guid.
        If the source file doesn't exist, create it with an empty structure.
        
        Parameters:
            source_path: Path to the source file
            context_data: Context data containing source_guid
            
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
                
                # Extract source_guid from context_data (handle nested structure)
                source_guid = None
                if isinstance(context_data, dict):
                    # Check top level first
                    if "source_guid" in context_data:
                        source_guid = context_data["source_guid"]
                    else:
                        # Check nested structure
                        for _, value in context_data.items():
                            if isinstance(value, dict) and "source_guid" in value:
                                source_guid = value["source_guid"]
                                break
                
                if source_guid:
                    # Look for the source_guid in the source data array
                    for item in source_data:
                        if isinstance(item, dict) and item.get("source_guid") == source_guid:
                            # Return the item without the source_guid field for clean content
                            clean_item = {k: v for k, v in item.items() if k != "source_guid"}
                            return clean_item
            return None
        except Exception as e:
            from agent_actions.shared.exceptions import FileLoadError
            raise FileLoadError(
                str(source_path),
                "Failed to load or create source content",
                context={'source_guid': source_guid, 'operation': 'load_source_content'},
                cause=e
            )
            
    @staticmethod
    def save_source_content(source_path: Path, source_guid: str, content: Any) -> None:
        """
        Save content to source file.
        
        Args:
            source_path: Path to the source file
            source_guid: source_guid to associate with the content
            content: Content to save
        """
        try:
            ServiceLogger.log_operation_start(logger, "save source content", 
                                           source_path=str(source_path), source_guid=source_guid)
            
            # Ensure source directory exists
            SourcePathManager.ensure_source_directory(source_path)
            
            # Load existing content or create new list
            if source_path.exists():
                with open(source_path, 'r') as file:
                    source_data = json.load(file)
            else:
                source_data = []
                
            # Update or append content in array format
            content_entry = content.copy() if isinstance(content, dict) else content
            if isinstance(content_entry, dict):
                content_entry["source_guid"] = source_guid
            
            updated = False
            for i, item in enumerate(source_data):
                if isinstance(item, dict) and item.get("source_guid") == source_guid:
                    source_data[i] = content_entry
                    updated = True
                    break
                    
            if not updated:
                source_data.append(content_entry)
                
            # Save updated content
            with open(source_path, 'w') as file:
                json.dump(source_data, file, indent=2)
                
            ServiceLogger.log_operation_success(logger, "save source content", 
                                             source_guid=source_guid)
            
        except Exception as e:
            ServiceLogger.log_operation_error(logger, "save source content", e)
            raise 