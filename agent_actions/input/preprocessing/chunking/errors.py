"""
Chunking-specific error classes shared across strategies.
"""


class FieldChunkingError(Exception):
    """Raised when field chunking operations fail."""


class FieldChunkingValidationError(ValueError):
    """Raised when field chunking configuration is invalid."""


__all__ = ["FieldChunkingError", "FieldChunkingValidationError"]
