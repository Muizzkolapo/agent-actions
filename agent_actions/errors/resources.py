"""Resource-related errors (memory, dependencies, etc)."""
# pylint: disable=unnecessary-pass
# Unnecessary-pass: Simple exception classes inherit all behavior from parent

from agent_actions.errors.base import AgentActionsError


class ResourceError(AgentActionsError):
    """Base exception for resource-related errors."""
    pass


class ResourceMemoryError(ResourceError):
    """Raised when memory-related issues occur.

    Note: Renamed from MemoryError to avoid shadowing Python's built-in.
    For application-level memory management issues in agent-actions.
    """
    pass


class DependencyError(ResourceError):
    """Raised when a required dependency is not provided or cannot be loaded."""
    pass
