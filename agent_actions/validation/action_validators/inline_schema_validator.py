"""Validator for inline schema configuration."""

from agent_actions.utils.constants import SCHEMA_KEY, SCHEMA_NAME_KEY
from agent_actions.utils.schema_utils import is_compiled_schema
from agent_actions.validation.action_validators.base_action_validator import (
    ActionEntryValidationResult,
    BaseActionEntryValidator,
)
from agent_actions.validation.utils.schema_type_validator import SchemaTypeValidator


class InlineSchemaValidator(BaseActionEntryValidator):
    """Validates inline schema configuration for shorthand and compiled formats."""

    def __init__(self):
        """Initialize with schema type validator."""
        self.schema_type_validator = SchemaTypeValidator()

    def validate(self, context) -> ActionEntryValidationResult:
        """Validate inline schema configuration."""
        normalized_entry = context.normalized_entry
        desc = context.description

        errors = []
        warnings = []

        if SCHEMA_KEY not in normalized_entry:
            return ActionEntryValidationResult.success()

        inline_schema = normalized_entry[SCHEMA_KEY]

        if not isinstance(inline_schema, dict):
            errors.append(
                f"{desc} 'schema' must be a dictionary with field names "
                f"as keys and types as values."
            )
            return ActionEntryValidationResult.with_errors(errors)

        # Unified/compiled schemas are validated during render
        if is_compiled_schema(inline_schema):
            if SCHEMA_NAME_KEY in normalized_entry:
                warnings.append(
                    f"{desc} has both 'schema' and 'schema_name' defined. "
                    f"The inline 'schema' will take precedence over 'schema_name'."
                )
            if warnings:
                return ActionEntryValidationResult(errors=[], warnings=warnings)
            return ActionEntryValidationResult.success()

        valid_types = {"string", "number", "integer", "boolean", "array", "object"}
        valid_array_types = {
            "array[string]",
            "array[number]",
            "array[integer]",
            "array[boolean]",
            "array[object]",
        }

        for field_name, field_type in inline_schema.items():
            if not isinstance(field_name, str):
                errors.append(
                    f"{desc} 'schema' keys must be strings, found {type(field_name).__name__}."
                )
                continue

            if not isinstance(field_type, str):
                if isinstance(field_type, dict):
                    # Dict values are valid nested JSON Schema property
                    # definitions (e.g. {type: array, items: {type: string}}).
                    continue
                errors.append(
                    f"{desc} 'schema' value for field '{field_name}' must be "
                    f"a string or dict type, found {type(field_type).__name__}."
                )
                continue

            base_type = field_type.rstrip("!")

            if not self.schema_type_validator.is_valid_schema_type(
                base_type, valid_types, valid_array_types
            ):
                all_valid = sorted(valid_types | valid_array_types)
                errors.append(
                    f"{desc} 'schema' field '{field_name}' has invalid type "
                    f"'{base_type}'. Valid types are: {', '.join(all_valid)} "
                    f"or array[object:{{'prop': 'type'}}]"
                )

        if SCHEMA_NAME_KEY in normalized_entry:
            warnings.append(
                f"{desc} has both 'schema' and 'schema_name' defined. "
                f"The inline 'schema' will take precedence over 'schema_name'."
            )

        if errors or warnings:
            return ActionEntryValidationResult(errors=errors, warnings=warnings)

        return ActionEntryValidationResult.success()
