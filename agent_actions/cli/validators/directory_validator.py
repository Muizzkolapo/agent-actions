"""
Directory validation utilities.
"""

from pathlib import Path
from typing import List


class DirectoryValidator:
    """Handles directory validation operations."""
    
    @staticmethod
    def check_required_directories(required_dirs: List[Path]) -> None:
        """
        Check if required directories exist.

        Args:
            required_dirs: List of directory paths to check.
            
        Raises:
            ValueError: If any required directory does not exist.
        """
        for directory in required_dirs:
            if not directory.exists():
                raise ValueError(f"Required directory does not exist: {directory}")