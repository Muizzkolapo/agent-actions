"""Validation-related errors."""

from agent_actions.errors.base import AgentActionsError


class ValidationError(AgentActionsError):
    """Base exception for validation failures."""
    pass


class PromptValidationError(ValidationError):
    """Raised when prompt validation fails."""
    pass


class DataValidationError(ValidationError):
    """Raised when data validation fails."""
    pass


class SchemaValidationError(ValidationError):
    """Raised when schema validation fails."""
    pass
