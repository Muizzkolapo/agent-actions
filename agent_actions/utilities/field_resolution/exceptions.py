"""
Custom exceptions for field resolution operations.

Provides specific exception types for different error scenarios:
- InvalidReferenceError: Malformed field reference syntax
- ReferenceNotFoundError: Referenced action or field not found in context
- DependencyValidationError: Reference violates dependency graph constraints
"""


class FieldResolutionError(Exception):
    """Base exception for all field resolution errors."""

    pass


class InvalidReferenceError(FieldResolutionError):
    """
    Raised when a field reference has invalid syntax.

    Examples of invalid references:
    - Empty string
    - Missing dot separator: "actionfield"
    - Empty components: "action." or ".field"
    """

    pass


class ReferenceNotFoundError(FieldResolutionError):
    """
    Raised when a referenced action or field cannot be found in context.

    This typically occurs when:
    - The action name doesn't exist in the field context
    - The field path doesn't exist within the action's data
    """

    pass


class DependencyValidationError(FieldResolutionError):
    """
    Raised when a field reference violates dependency graph constraints.

    Occurs when:
    - Referenced action is not in the workflow
    - Referenced action is not upstream of the current action
    - Referenced action is not declared in dependencies (strict mode)
    """

    pass
