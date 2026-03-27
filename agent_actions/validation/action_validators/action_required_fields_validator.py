"""Validator for required action configuration fields."""

from agent_actions.validation.action_validators.base_action_validator import (
    ActionEntryValidationResult,
    BaseActionEntryValidator,
)
from agent_actions.validation.utils.action_config_validation_utilities import (
    ActionConfigValidationUtilities,
)


class ActionRequiredFieldsValidator(BaseActionEntryValidator):
    """Validates that all required action fields are present."""

    def validate(self, context) -> ActionEntryValidationResult:
        """Check that all required fields are present in entry."""
        normalized_entry = context.normalized_entry
        desc = context.description

        required_keys = ActionConfigValidationUtilities.get_required_action_keys()
        present_keys = set(normalized_entry.keys())
        missing_keys = required_keys - present_keys

        if missing_keys:
            sorted_missing = sorted(missing_keys)
            error_msg = f"{desc} missing required key(s): {', '.join(sorted_missing)}."
            return ActionEntryValidationResult.with_errors([error_msg])

        return ActionEntryValidationResult.success()
