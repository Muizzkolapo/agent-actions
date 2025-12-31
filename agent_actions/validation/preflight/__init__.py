"""Pre-flight validation package for unified batch/online validation.

This package provides validators that run before any LLM calls to catch
configuration and input errors early, with consistent error messaging
across both batch and online execution modes.

Includes static type checking for workflow data flow validation.
"""

from agent_actions.validation.preflight.error_formatter import (
    PreFlightErrorFormatter,
    ValidationIssue,
)
from agent_actions.validation.preflight.template_variable_validator import (
    TemplateVariableValidator,
)
from agent_actions.validation.preflight.context_structure_validator import (
    ContextStructureValidator,
)
from agent_actions.validation.preflight.path_validator import PathValidator
from agent_actions.validation.preflight.vendor_compatibility_validator import (
    VendorCompatibilityValidator,
)
from agent_actions.validation.preflight.dependency_validator import DependencyValidator
from agent_actions.validation.preflight.preflight_validator import (
    PreFlightValidator,
    PreFlightValidationResult,
    validate_preflight,
)

# Static type checking
from agent_actions.validation.static_analyzer import (
    WorkflowStaticAnalyzer,
    analyze_workflow,
    StaticValidationResult,
    StaticTypeError,
    StaticTypeWarning,
)

__all__ = [
    # Error formatting
    "PreFlightErrorFormatter",
    "ValidationIssue",
    # Validators
    "TemplateVariableValidator",
    "ContextStructureValidator",
    "PathValidator",
    "VendorCompatibilityValidator",
    "DependencyValidator",
    # Orchestrator
    "PreFlightValidator",
    "PreFlightValidationResult",
    "validate_preflight",
    # Static type checking
    "WorkflowStaticAnalyzer",
    "analyze_workflow",
    "StaticValidationResult",
    "StaticTypeError",
    "StaticTypeWarning",
]
