"""Validator for required agent configuration fields."""

from agent_actions.validation.agent_validators.base_agent_validator import (
    BaseAgentEntryValidator,
    AgentEntryValidationResult,
)
from agent_actions.validation.utils.agent_config_validation_utilities import (
    AgentConfigValidationUtilities,
)


class AgentRequiredFieldsValidator(BaseAgentEntryValidator):
    """Validates that all required agent fields are present."""

    def validate(self, context) -> AgentEntryValidationResult:
        """Check that all required fields are present in entry."""
        normalized_entry = context.normalized_entry
        desc = context.description

        required_keys = AgentConfigValidationUtilities.get_required_agent_keys()
        present_keys = set(normalized_entry.keys())
        missing_keys = required_keys - present_keys

        if missing_keys:
            sorted_missing = sorted(missing_keys)
            error_msg = f"{desc} missing required key(s): {', '.join(sorted_missing)}."
            return AgentEntryValidationResult.with_errors([error_msg])

        return AgentEntryValidationResult.success()
