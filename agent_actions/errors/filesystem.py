"""File system operation errors."""

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
