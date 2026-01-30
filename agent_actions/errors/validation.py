"""Validation-related errors."""
# Unnecessary-pass: Simple exception classes inherit all behavior from parent

from typing import Any, Dict, List, Optional, Tuple

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
    """Raised when schema validation fails.

    Provides structured context for debugging schema validation issues,
    including validation type, field mismatches, and actionable hints.

    Args:
        message: Description of the validation failure
        schema_name: Name of the schema being validated
        validation_type: Type of validation ('input', 'output', 'structure', 'compilation')
        action_name: Name of the action/agent being validated
        expected_fields: List of fields expected by the schema
        actual_fields: List of fields actually present
        missing_fields: Required fields that are missing
        extra_fields: Fields present but not in schema
        type_errors: Dict mapping field names to (expected_type, actual_type) tuples
        error_path: JSON path to the failing field (e.g., "root.items[0].name")
        failed_value: The value that failed validation
        schema_constraint: The schema constraint that failed
        hint: Actionable suggestion for fixing the error
        context: Additional context dict
        cause: Original exception (e.g., from jsonschema)
    """

    def __init__(
        self,
        message: str,
        *,
        schema_name: Optional[str] = None,
        validation_type: Optional[str] = None,
        action_name: Optional[str] = None,
        expected_fields: Optional[List[str]] = None,
        actual_fields: Optional[List[str]] = None,
        missing_fields: Optional[List[str]] = None,
        extra_fields: Optional[List[str]] = None,
        type_errors: Optional[Dict[str, Tuple[str, str]]] = None,
        error_path: Optional[str] = None,
        failed_value: Optional[Any] = None,
        schema_constraint: Optional[Dict[str, Any]] = None,
        hint: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        ctx = context or {}

        # Populate context from specific parameters
        if schema_name is not None:
            ctx["schema_name"] = schema_name
        if validation_type is not None:
            ctx["validation_type"] = validation_type
        if action_name is not None:
            ctx["action_name"] = action_name
        if expected_fields is not None:
            ctx["expected_fields"] = expected_fields
        if actual_fields is not None:
            ctx["actual_fields"] = actual_fields
        if missing_fields is not None:
            ctx["missing_fields"] = missing_fields
        if extra_fields is not None:
            ctx["extra_fields"] = extra_fields
        if type_errors is not None:
            ctx["type_errors"] = type_errors
        if error_path is not None:
            ctx["error_path"] = error_path
        if failed_value is not None:
            ctx["failed_value"] = failed_value
        if schema_constraint is not None:
            ctx["schema_constraint"] = schema_constraint
        if hint is not None:
            ctx["hint"] = hint

        super().__init__(message, context=ctx, cause=cause)

        # Store as instance attributes for easy programmatic access
        self.schema_name = schema_name
        self.validation_type = validation_type
        self.action_name = action_name
        self.expected_fields = expected_fields or []
        self.actual_fields = actual_fields or []
        self.missing_fields = missing_fields or []
        self.extra_fields = extra_fields or []
        self.type_errors = type_errors or {}
        self.error_path = error_path
        self.failed_value = failed_value
        self.schema_constraint = schema_constraint
        self.hint = hint

    def __str__(self) -> str:
        """Return user-friendly string representation."""
        return self.format_user_message()

    def format_user_message(self) -> str:
        """Format a user-friendly error message with all details."""
        lines = [self.args[0]]  # Just the message

        # Schema and action context
        if self.schema_name or self.action_name:
            lines.append("")
            if self.schema_name:
                lines.append(f"  Schema: {self.schema_name}")
            if self.action_name:
                lines.append(f"  Action: {self.action_name}")
            if self.validation_type:
                lines.append(f"  Validation: {self.validation_type}")

        # Field mismatches
        if self.missing_fields:
            lines.append("")
            lines.append(f"  Missing fields: {', '.join(self.missing_fields)}")

        if self.extra_fields:
            lines.append(f"  Extra fields: {', '.join(self.extra_fields)}")

        if self.type_errors:
            lines.append("")
            lines.append("  Type mismatches:")
            for field, (expected, actual) in self.type_errors.items():
                lines.append(f"    - {field}: expected {expected}, got {actual}")

        # Error path for nested validation errors
        if self.error_path:
            lines.append("")
            lines.append(f"  Error path: {self.error_path}")

        # Hint
        if self.hint:
            lines.append("")
            lines.append(f"  Hint: {self.hint}")

        return "\n".join(lines)
