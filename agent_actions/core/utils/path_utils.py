"""
Utility functions for common path operations.

This module provides convenience functions that consolidate the most frequently
duplicated path logic identified across the codebase.
"""

from pathlib import Path
from typing import Optional, Union
import logging

from agent_actions.core.context.path_manager import PathManager
from agent_actions.core.context.path_config import PathConfigManager

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


def create_side_output_directory(output_directory: Union[str, Path]) -> Path:
    """
    Create side output directory following the standard pattern.
    
    This replaces the duplicated pattern:
    side_output_dir = Path(output_directory).parent / 'side_output'
    
    Args:
        output_directory: Base output directory path
        
    Returns:
        Path to side output directory
    """
    output_path = Path(output_directory)
    side_output_dir = output_path.parent / 'side_output'
    return ensure_directory_exists(side_output_dir)


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


def check_path_exists(path: Union[str, Path]) -> bool:
    """
    Check if a path exists.
    
    This provides a consistent interface for the frequently used:
    path.exists() pattern
    
    Args:
        path: Path to check
        
    Returns:
        True if path exists
    """
    return Path(path).exists()


def find_project_root(start_path: Optional[Path] = None, marker_file: str = "agent_actions.yml") -> Path:
    """
    Find project root by looking for marker file.
    
    This consolidates the project root discovery logic.
    
    Args:
        start_path: Starting point for search
        marker_file: Name of marker file to look for
        
    Returns:
        Path to project root
        
    Raises:
        ProjectRootNotFoundError: If project root cannot be found
    """
    config = PathConfigManager()
    pm = PathManager()
    return pm.get_project_root(start_path)


def create_mirror_source_path(target_path: Union[str, Path]) -> Path:
    """
    Create source path by mirroring target path structure.
    
    This replaces the complex logic in SourceDataLoader and similar components.
    
    Args:
        target_path: Original target path
        
    Returns:
        Mirrored source path
    """
    return get_path_manager().create_mirror_path(Path(target_path), "target", "source")


def validate_path_permissions(path: Union[str, Path], readable: bool = False, writable: bool = False) -> bool:
    """
    Validate path permissions.
    
    This consolidates the permission checking logic found in validators.
    
    Args:
        path: Path to validate
        readable: Check if path is readable
        writable: Check if path is writable
        
    Returns:
        True if path meets all permission requirements
    """
    requirements = {}
    if readable:
        requirements["must_be_readable"] = True
    if writable:
        requirements["must_be_writable"] = True
        
    try:
        return get_path_manager().validate_path(Path(path), requirements)
    except Exception:
        return False


def clean_directory(directory: Union[str, Path], recursive: bool = False) -> bool:
    """
    Clean/remove a directory.
    
    Args:
        directory: Directory to clean
        recursive: Remove contents recursively
        
    Returns:
        True if successfully cleaned
    """
    return get_path_manager().clean_path(Path(directory), recursive=recursive)


def get_relative_path(path: Union[str, Path], base: Union[str, Path]) -> Path:
    """
    Get path relative to base directory.
    
    Args:
        path: Absolute path
        base: Base directory
        
    Returns:
        Path relative to base
    """
    abs_path = resolve_absolute_path(path)
    abs_base = resolve_absolute_path(base)
    return abs_path.relative_to(abs_base)


def find_files_by_extension(directory: Union[str, Path], extension: str) -> list[Path]:
    """
    Find all files with specific extension in directory.
    
    Args:
        directory: Directory to search
        extension: File extension (with or without dot)
        
    Returns:
        List of matching file paths
    """
    if not extension.startswith('.'):
        extension = f'.{extension}'
    
    pattern = f"**/*{extension}"
    return get_path_manager().find_files_by_pattern(pattern, Path(directory))


def safe_path_join(*parts: Union[str, Path]) -> Path:
    """
    Safely join path parts, ensuring result is within project bounds.
    
    Args:
        *parts: Path parts to join
        
    Returns:
        Joined path
        
    Raises:
        ValueError: If resulting path would be outside project
    """
    joined_path = Path()
    for part in parts:
        joined_path = joined_path / Path(part)
    
    resolved_path = resolve_absolute_path(joined_path)
    
    # Check if path is within project bounds
    pm = get_path_manager()
    if not pm.is_within_project(resolved_path):
        raise ValueError(f"Path {resolved_path} is outside project bounds")
    
    return resolved_path


def create_agent_directory_structure(agent_name: str, base_path: Optional[Path] = None) -> dict[str, Path]:
    """
    Create standard agent directory structure.
    
    This consolidates the agent directory creation logic.
    
    Args:
        agent_name: Name of the agent
        base_path: Base path for agent directories (defaults to project root)
        
    Returns:
        Dictionary of created directory paths
    """
    pm = get_path_manager()
    
    if base_path is None:
        base_path = pm.get_project_root()
    
    # Get standard agent paths
    agent_paths = pm.get_agent_paths(agent_name)
    
    # Ensure all directories exist
    created_paths = {}
    for name, path in agent_paths.items():
        created_paths[name] = ensure_directory_exists(path)
    
    logger.info(f"Created agent directory structure for {agent_name}")
    return created_paths


# Convenience constants for common operations
DEFAULT_MARKER_FILE = "agent_actions.yml"
COMMON_EXTENSIONS = ['.json', '.yml', '.yaml', '.txt', '.py']
SIDE_OUTPUT_DIR_NAME = "side_output"


# Backward compatibility aliases for existing code
def mkdir_with_parents(path: Union[str, Path]) -> Path:
    """Backward compatibility alias for ensure_directory_exists."""
    return ensure_directory_exists(path)


def get_absolute_path(path: Union[str, Path]) -> Path:
    """Backward compatibility alias for resolve_absolute_path."""
    return resolve_absolute_path(path)