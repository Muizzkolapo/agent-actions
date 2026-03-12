"""Validation-related errors."""

from typing import Any

from agent_actions.errors.base import AgentActionsError
from agent_actions.errors.preflight import _render_sections


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

    def __init__(
        self,
        message: str,
        *,
        schema_name: str | None = None,
        validation_type: str | None = None,
        action_name: str | None = None,
        expected_fields: list[str] | None = None,
        actual_fields: list[str] | None = None,
        missing_fields: list[str] | None = None,
        extra_fields: list[str] | None = None,
        type_errors: dict[str, tuple[str, str]] | None = None,
        error_path: str | None = None,
        failed_value: Any | None = None,
        schema_constraint: dict[str, Any] | None = None,
        hint: str | None = None,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        ctx = dict(context) if context else {}
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
        return self.format_user_message()

    def format_user_message(self) -> str:
        sections: list = [
            None,
            ("Schema", self.schema_name),
            ("Action", self.action_name),
            ("Validation", self.validation_type),
            None,
            ("Missing fields", self.missing_fields or None),
            ("Extra fields", self.extra_fields or None),
        ]

        if self.type_errors:
            sections.append(None)
            sections.append("  Type mismatches:")
            for field, (expected, actual) in self.type_errors.items():
                sections.append(f"    - {field}: expected {expected}, got {actual}")

        sections.extend(
            [
                None,
                ("Error path", self.error_path),
                None,
                ("Hint", self.hint),
            ]
        )

        return _render_sections(self.args[0], sections)
