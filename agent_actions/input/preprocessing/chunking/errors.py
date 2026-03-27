"""Chunking-specific error classes shared across strategies."""

from agent_actions.errors.processing import ProcessingError
from agent_actions.errors.validation import ValidationError


class FieldChunkingError(ProcessingError):
    """Raised when field chunking operations fail."""


class FieldChunkingValidationError(ValidationError):
    """Raised when field chunking configuration is invalid."""


__all__ = ["FieldChunkingError", "FieldChunkingValidationError"]
