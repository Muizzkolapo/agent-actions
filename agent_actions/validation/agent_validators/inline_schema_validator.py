"""
Validator for inline schema configuration.
"""

from agent_actions.validation.agent_validators.base_agent_validator import (
    BaseAgentEntryValidator,
    AgentEntryValidationResult,
)
from agent_actions.validation.utils.schema_type_validator import SchemaTypeValidator
from agent_actions.utils.constants import SCHEMA_KEY, SCHEMA_NAME_KEY
from agent_actions.utils.schema_utils import is_compiled_schema


class InlineSchemaValidator(BaseAgentEntryValidator):
    """
    Validates inline schema configuration.

    Handles two schema formats:
    1. Inline shorthand: {field_name: type_string} - validated for valid types
    2. Unified/compiled format: {name: ..., fields: [...]} - already validated during render

    Also warns if both 'schema' and 'schema_name' are present.

    Complexity: CC ~6
    """

    def __init__(self):
        """Initialize with schema type validator."""
        self.schema_type_validator = SchemaTypeValidator()

    def validate(self, context) -> AgentEntryValidationResult:
        """
        Validate inline schema configuration.

        Args:
            context: Validation context

        Returns:
            Validation result with errors/warnings
        """
        normalized_entry = context.normalized_entry
        desc = context.description

        errors = []
        warnings = []

        # Only validate if 'schema' key is present
        if SCHEMA_KEY not in normalized_entry:
            return AgentEntryValidationResult.success()

        inline_schema = normalized_entry[SCHEMA_KEY]

        # Check schema is a dictionary
        if not isinstance(inline_schema, dict):
            errors.append(
                f"{desc} 'schema' must be a dictionary with field names "
                f"as keys and types as values."
            )
            return AgentEntryValidationResult.with_errors(errors)

        # Skip validation for unified/compiled schema format
        # These schemas are already validated during the render step
        if is_compiled_schema(inline_schema):
            # Still check for schema_name conflict
            if SCHEMA_NAME_KEY in normalized_entry:
                warnings.append(
                    f"{desc} has both 'schema' and 'schema_name' defined. "
                    f"The inline 'schema' will take precedence over 'schema_name'."
                )
            if warnings:
                return AgentEntryValidationResult(errors=[], warnings=warnings)
            return AgentEntryValidationResult.success()

        # Validate inline shorthand format: {field_name: type_string}
        # Define valid schema types
        valid_types = {"string", "number", "integer", "boolean", "array", "object"}
        valid_array_types = {
            "array[string]",
            "array[number]",
            "array[integer]",
            "array[boolean]",
            "array[object]",
        }

        # Validate each field in the schema
        for field_name, field_type in inline_schema.items():
            # Check field name is string
            if not isinstance(field_name, str):
                errors.append(
                    f"{desc} 'schema' keys must be strings, found {type(field_name).__name__}."
                )
                continue

            # Check field type is string
            if not isinstance(field_type, str):
                errors.append(
                    f"{desc} 'schema' value for field '{field_name}' must be "
                    f"a string type, found {type(field_type).__name__}."
                )
                continue

            # Strip trailing '!' (required marker)
            base_type = field_type.rstrip("!")

            # Validate the type using SchemaTypeValidator
            if not self.schema_type_validator.is_valid_schema_type(
                base_type, valid_types, valid_array_types
            ):
                all_valid = sorted(valid_types | valid_array_types)
                errors.append(
                    f"{desc} 'schema' field '{field_name}' has invalid type "
                    f"'{base_type}'. Valid types are: {', '.join(all_valid)} "
                    f"or array[object:{{'prop': 'type'}}]"
                )

        # Warn if both 'schema' and 'schema_name' are present
        if SCHEMA_NAME_KEY in normalized_entry:
            warnings.append(
                f"{desc} has both 'schema' and 'schema_name' defined. "
                f"The inline 'schema' will take precedence over 'schema_name'."
            )

        if errors or warnings:
            return AgentEntryValidationResult(errors=errors, warnings=warnings)

        return AgentEntryValidationResult.success()
