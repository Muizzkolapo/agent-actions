"""Context structure validator for pre-flight validation.

Validates that context data structure matches expected schema requirements,
checking for required fields and proper types before any LLM processing.
"""

from typing import Any, Dict, List, Optional, Set, Type, Union

from agent_actions.validation.base_validator import BaseValidator
from agent_actions.validation.preflight.error_formatter import (
    PreFlightErrorFormatter,
    ValidationIssue,
)


class ContextStructureValidator(BaseValidator):
    """Validates that context data has the expected structure and fields.

    This validator checks that required fields are present in the context
    and that field types match expectations. This catches structure errors
    before template rendering or LLM calls.

    Attributes:
        issues: List of ValidationIssue objects found during validation
    """

    def __init__(self) -> None:
        super().__init__()
        self.issues: List[ValidationIssue] = []

    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        """Validate context structure against expected schema.

        Args:
            data: Dictionary containing:
                - 'context': The context data to validate
                - 'expected_fields': Optional list of required field names
                - 'field_types': Optional dict mapping field names to expected types
            config: Optional config with:
                - 'agent_name': Name of the agent for error messages
                - 'strict': If True, extra fields cause warnings
                - 'allow_none': If True, None values are acceptable

        Returns:
            bool: True if context structure is valid, False otherwise
        """
        self.clear_errors()
        self.clear_warnings()
        self.issues = []

        if not isinstance(data, dict):
            self.add_error("Validation data must be a dictionary with 'context' key.")
            return False

        context = data.get("context")
        expected_fields = data.get("expected_fields", [])
        field_types = data.get("field_types", {})
        config = config or {}

        agent_name = config.get("agent_name")
        strict = config.get("strict", False)
        allow_none = config.get("allow_none", True)

        # Validate context is a dict or can be treated as one
        if context is None:
            self.add_error("Context is None. Expected a dictionary or valid data.")
            self.issues.append(
                ValidationIssue(
                    message="Context is None",
                    issue_type="error",
                    category="context",
                    hint="Provide a valid context dictionary with required fields.",
                    agent_name=agent_name,
                )
            )
            return False

        if isinstance(context, str):
            # String context is valid for some use cases
            if expected_fields:
                self.add_error(
                    "Context is a string but expected fields were specified. "
                    "String context cannot have field validation."
                )
                self.issues.append(
                    ValidationIssue(
                        message="Context type mismatch",
                        issue_type="error",
                        category="context",
                        missing_refs=expected_fields,
                        hint="Provide context as a dictionary, not a string.",
                        agent_name=agent_name,
                    )
                )
                return False
            return True

        if not isinstance(context, dict):
            self.add_error(f"Context must be a dictionary, got {type(context).__name__}.")
            return False

        # Check required fields
        actual_fields = set(context.keys())
        missing_fields = self._find_missing_fields(expected_fields, actual_fields)

        if missing_fields:
            self.add_error(f"Missing required field(s) in context: {', '.join(missing_fields)}")
            self.issues.append(
                PreFlightErrorFormatter.create_context_structure_issue(
                    message="Context is missing required fields",
                    expected_fields=expected_fields,
                    actual_fields=list(actual_fields),
                    agent_name=agent_name,
                )
            )

        # Check field types
        type_errors = self._check_field_types(context, field_types, allow_none)
        for field_name, expected_type, actual_type in type_errors:
            self.add_error(
                f"Field '{field_name}' has wrong type: expected {expected_type}, got {actual_type}"
            )
            self.issues.append(
                ValidationIssue(
                    message=f"Field type mismatch for '{field_name}'",
                    issue_type="error",
                    category="context",
                    hint=f"Change '{field_name}' to type {expected_type}.",
                    agent_name=agent_name,
                    extra_context={
                        "field": field_name,
                        "expected_type": expected_type,
                        "actual_type": actual_type,
                    },
                )
            )

        # Check for None values if not allowed
        if not allow_none:
            none_fields = [k for k, v in context.items() if v is None]
            if none_fields:
                self.add_warning(f"Field(s) with None value: {', '.join(none_fields)}")

        # Check for unexpected fields (strict mode)
        if strict and expected_fields:
            extra_fields = actual_fields - set(expected_fields)
            if extra_fields:
                self.add_warning(f"Unexpected field(s) in context: {', '.join(extra_fields)}")

        return not self.has_errors()

    def validate_context(
        self,
        context: Union[Dict[str, Any], str, None],
        expected_fields: Optional[List[str]] = None,
        field_types: Optional[Dict[str, Type]] = None,
        agent_name: Optional[str] = None,
    ) -> bool:
        """Convenience method to validate context directly.

        Args:
            context: The context to validate
            expected_fields: Optional list of required field names
            field_types: Optional dict mapping field names to expected types
            agent_name: Optional agent name for error messages

        Returns:
            bool: True if context is valid, False otherwise
        """
        data = {
            "context": context,
            "expected_fields": expected_fields or [],
            "field_types": field_types or {},
        }
        config = {"agent_name": agent_name}
        return self.validate(data, config)

    def _find_missing_fields(self, expected: List[str], actual: Set[str]) -> List[str]:
        """Find fields that are expected but not present.

        Args:
            expected: List of expected field names
            actual: Set of actual field names in context

        Returns:
            List of missing field names
        """
        return [f for f in expected if f not in actual]

    def _check_field_types(
        self,
        context: Dict[str, Any],
        field_types: Dict[str, Type],
        allow_none: bool,
    ) -> List[tuple]:
        """Check that field values have expected types.

        Args:
            context: The context dictionary
            field_types: Dict mapping field names to expected types
            allow_none: If True, None values pass type check

        Returns:
            List of (field_name, expected_type, actual_type) tuples for failures
        """
        errors = []

        for field_name, expected_type in field_types.items():
            if field_name not in context:
                continue  # Missing fields handled separately

            value = context[field_name]

            # Handle None values
            if value is None:
                if not allow_none:
                    errors.append((field_name, expected_type.__name__, "None"))
                continue

            # Check type
            if not isinstance(value, expected_type):
                actual_type = type(value).__name__
                expected_name = (
                    expected_type.__name__
                    if hasattr(expected_type, "__name__")
                    else str(expected_type)
                )
                errors.append((field_name, expected_name, actual_type))

        return errors

    def get_issues(self) -> List[ValidationIssue]:
        """Get the list of validation issues found.

        Returns:
            List of ValidationIssue objects
        """
        return self.issues
