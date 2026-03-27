"""Validator for optional field types in action configuration."""

from agent_actions.utils.constants import JSON_MODE_KEY
from agent_actions.validation.action_validators.base_action_validator import (
    ActionEntryValidationResult,
    BaseActionEntryValidator,
)


class OptionalFieldTypeValidator(BaseActionEntryValidator):
    """Validates types of optional configuration fields."""

    def validate(self, context) -> ActionEntryValidationResult:
        """Validate optional field types."""
        errors: list[str] = []

        self._validate_description_field(context, errors)
        self._validate_version_field(context, errors)
        self._validate_dependencies_field(context, errors)
        self._validate_boolean_fields(context, errors)

        if errors:
            return ActionEntryValidationResult.with_errors(errors)

        return ActionEntryValidationResult.success()

    def _validate_description_field(self, context, errors: list) -> None:
        """Validate description field type."""
        if "description" in context.normalized_entry:
            if not isinstance(context.normalized_entry["description"], str):
                errors.append(f"{context.description} 'description' should be a string.")

    def _validate_version_field(self, context, errors: list) -> None:
        """Validate version field type."""
        if "version" in context.normalized_entry:
            if not isinstance(context.normalized_entry["version"], str | int | float):
                errors.append(f"{context.description} 'version' should be a string or number.")

    def _validate_dependencies_field(self, context, errors: list) -> None:
        """Validate dependencies field type."""
        if "dependencies" in context.normalized_entry:
            if not isinstance(context.normalized_entry["dependencies"], list):
                errors.append(f"{context.description} 'dependencies' should be a list.")

    def _validate_boolean_fields(self, context, errors: list) -> None:
        """Validate boolean field types."""
        normalized_entry = context.normalized_entry
        desc = context.description

        if "is_operational" in normalized_entry:
            if not isinstance(normalized_entry["is_operational"], bool):
                errors.append(f"{desc} 'is_operational' should be a boolean.")

        if JSON_MODE_KEY in normalized_entry:
            if not isinstance(normalized_entry[JSON_MODE_KEY], bool):
                errors.append(f"{desc} 'json_mode' should be a boolean.")

        if "prompt_debug" in normalized_entry:
            if not isinstance(normalized_entry["prompt_debug"], bool):
                errors.append(f"{desc} 'prompt_debug' should be a boolean.")
