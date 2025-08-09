"""
Utility modules for agent-actions.

This package provides common utility functions and classes used across the agent-actions codebase.
"""

from .path_utils import (
    ensure_directory_exists,
    create_side_output_directory,
    resolve_absolute_path,
    check_path_exists,
    find_project_root,
    create_mirror_source_path,
    validate_path_permissions,
    clean_directory,
    get_relative_path,
    find_files_by_extension,
    safe_path_join,
    create_agent_directory_structure,
    get_path_manager,
    
    # Backward compatibility aliases
    mkdir_with_parents,
    get_absolute_path,
    
    # Constants
    DEFAULT_MARKER_FILE,
    COMMON_EXTENSIONS,
    SIDE_OUTPUT_DIR_NAME,
)

from .field_chunking import FieldAnalyzer, FieldChunker, FieldAnalysisResult

__all__ = [
    "ensure_directory_exists",
    "create_side_output_directory", 
    "resolve_absolute_path",
    "check_path_exists",
    "find_project_root",
    "create_mirror_source_path",
    "validate_path_permissions",
    "clean_directory",
    "get_relative_path",
    "find_files_by_extension",
    "safe_path_join",
    "create_agent_directory_structure",
    "get_path_manager",
    "mkdir_with_parents",
    "get_absolute_path",
    "DEFAULT_MARKER_FILE",
    "COMMON_EXTENSIONS",
    "SIDE_OUTPUT_DIR_NAME",
    "FieldAnalyzer",
    "FieldAnalysisResult",
    "FieldChunker",
]
