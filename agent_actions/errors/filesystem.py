"""File system operation errors."""
# pylint: disable=unnecessary-pass
# Unnecessary-pass: Simple exception classes inherit all behavior from parent

from agent_actions.errors.base import AgentActionsError


class FileSystemError(AgentActionsError):
    """Base exception for file system operations."""
    pass


class FileLoadError(FileSystemError):
    """Raised when a file cannot be loaded."""
    pass


class FileWriteError(FileSystemError):
    """Raised when a file cannot be written."""
    pass


class DirectoryError(FileSystemError):
    """Raised when directory operations fail."""
    pass
