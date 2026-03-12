"""Centralized field reference parsing and resolution."""

from .resolver import (
    FieldReferenceResolver,
    ResolvedReference,
)
from .reference_parser import (
    ReferenceParser,
    ParsedReference,
    ReferenceFormat,
)
from .context_provider import (
    EvaluationContextProvider,
    EvaluationContext,
)
from .validator import ReferenceValidator
from agent_actions.utils.constants import SPECIAL_NAMESPACES
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
