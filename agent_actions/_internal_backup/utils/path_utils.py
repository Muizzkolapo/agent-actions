"""
Utility functions for common path operations.

This module provides convenience functions that consolidate the most frequently
duplicated path logic identified across the codebase.
"""

from pathlib import Path
from typing import Optional, Union
import logging

from agent_actions.state_management.path_manager import PathManager

logger = logging.getLogger(__name__)

# Global PathManager instance for convenience functions
_global_path_manager: Optional[PathManager] = None


def get_path_manager() -> PathManager:
    """
    Get the global PathManager instance.
    
    Returns:
        Global PathManager instance
    """
    global _global_path_manager
    if _global_path_manager is None:
        _global_path_manager = PathManager()
    return _global_path_manager


def ensure_directory_exists(path: Union[str, Path], is_file: bool = False) -> Path:
    """
    Ensure a directory exists, creating it if necessary.
    
    This replaces the most common duplicated pattern:
    path.parent.mkdir(parents=True, exist_ok=True)
    
    Args:
        path: Path to ensure exists
        is_file: If True, ensures parent directory exists for file path
        
    Returns:
        Resolved path
    """
    return get_path_manager().ensure_path_exists(Path(path), is_file=is_file)


def resolve_absolute_path(path: Union[str, Path]) -> Path:
    """
    Resolve path to absolute Path object.
    
    This replaces the duplicated pattern:
    resolved_path = str(Path(path).resolve())
    
    Args:
        path: Path to resolve
        
    Returns:
        Resolved absolute Path object
    """
    return get_path_manager().normalize_path(path)
