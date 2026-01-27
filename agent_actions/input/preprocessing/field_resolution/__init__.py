"""
Field Resolution Module - Centralized field reference parsing and resolution.
"""

# Core resolver
from .resolver import (
    FieldReferenceResolver,
    ResolvedReference,
)

# Parser and data classes
from .reference_parser import (
    ReferenceParser,
    ParsedReference,
    ReferenceFormat,
)

# Context provider
from .context_provider import (
    EvaluationContextProvider,
    EvaluationContext,
)

# Validator
from .validator import ReferenceValidator

# Re-export SPECIAL_NAMESPACES from centralized location
from agent_actions.utils.constants import SPECIAL_NAMESPACES

# Exceptions
from .exceptions import (
    FieldResolutionError,
    InvalidReferenceError,
    ReferenceNotFoundError,
    DependencyValidationError,
    SchemaFieldValidationError,
)


__all__ = [
    # Core resolver
    "FieldReferenceResolver",
    "ResolvedReference",
    # Parser
    "ReferenceParser",
    "ParsedReference",
    "ReferenceFormat",
    # Context
    "EvaluationContextProvider",
    "EvaluationContext",
    # Validation
    "ReferenceValidator",
    "SPECIAL_NAMESPACES",
    # Exceptions
    "FieldResolutionError",
    "InvalidReferenceError",
    "ReferenceNotFoundError",
    "DependencyValidationError",
    "SchemaFieldValidationError",
]
