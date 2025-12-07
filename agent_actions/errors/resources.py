"""Resource-related errors (memory, dependencies, etc)."""

from agent_actions.errors.base import AgentActionsError


class ResourceError(AgentActionsError):
    """Base exception for resource-related errors."""
    pass


class MemoryError(ResourceError):
    """Raised when memory-related issues occur.

    Note: This shadows Python's built-in MemoryError, but is scoped
    to agent-actions for application-level memory management issues.
    """
    pass


class DependencyError(ResourceError):
    """Raised when a required dependency is not provided or cannot be loaded."""
    pass
