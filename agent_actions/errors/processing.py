"""Processing and transformation errors."""

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


class EmptyOutputError(ProcessingError):
    """Raised when an action produces empty output and on_empty=error."""

    pass
