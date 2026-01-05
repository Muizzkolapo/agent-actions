"""Processing and transformation errors."""
# Unnecessary-pass: Simple exception classes inherit all behavior from parent

from agent_actions.errors.base import AgentActionsError


class ProcessingError(AgentActionsError):
    """Base exception for processing operations."""

    pass


class TransformationError(ProcessingError):
    """Raised when data transformation fails."""

    pass


class GenerationError(ProcessingError):
    """Raised when data generation fails."""

    pass


class WorkflowError(ProcessingError):
    """Raised when an error occurs in workflow processing."""

    pass


class SerializationError(ProcessingError):
    """Raised when serialization/deserialization fails."""

    pass
