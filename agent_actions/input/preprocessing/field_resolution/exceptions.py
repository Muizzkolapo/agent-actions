"""Custom exceptions for field resolution operations."""

from agent_actions.errors.processing import ProcessingError


class FieldResolutionError(ProcessingError):
    """Base exception for all field resolution errors."""


class InvalidReferenceError(FieldResolutionError):
    """Raised when a field reference has invalid syntax."""


class ReferenceNotFoundError(FieldResolutionError):
    """Raised when a referenced action or field cannot be found in context."""


class DependencyValidationError(FieldResolutionError):
    """Raised when a field reference violates dependency graph constraints."""


class SchemaFieldValidationError(FieldResolutionError):
    """Raised when a field reference doesn't match the action's output schema."""
