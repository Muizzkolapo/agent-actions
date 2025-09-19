"""
Compatibility module for core.path_manager imports.

This module re-exports PathManager from its new location to maintain
backward compatibility after the repository restructuring.
"""

# Re-export from new location
from .context.path_manager import *