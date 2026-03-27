"""Centralized field reference parsing and resolution."""

from agent_actions.utils.constants import SPECIAL_NAMESPACES

from .context_provider import (
    EvaluationContext,
    EvaluationContextProvider,
)
from .exceptions import (
    DependencyValidationError,
    FieldResolutionError,
    InvalidReferenceError,
    ReferenceNotFoundError,
    SchemaFieldValidationError,
)
from .reference_parser import (
    ParsedReference,
    ReferenceFormat,
    ReferenceParser,
)
from .resolver import (
    FieldReferenceResolver,
    ResolvedReference,
)
from .validator import ReferenceValidator

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
