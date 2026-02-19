"""Resource-related errors (memory, dependencies, etc)."""
# Unnecessary-pass: Simple exception classes inherit all behavior from parent

from agent_actions.errors.base import AgentActionsError


class ResourceError(AgentActionsError):
    """Base exception for resource-related errors."""

    pass


class DependencyError(ResourceError):
    """Raised when a required dependency is not provided or cannot be loaded."""

    pass
