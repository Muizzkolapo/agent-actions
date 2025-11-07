"""
Validator for required agent configuration fields.

Checks that all mandatory fields are present in the agent entry.
"""

from typing import Set
from agent_actions.validation.validators.base_agent_validator import (
    BaseAgentEntryValidator,
    AgentEntryValidationResult
)
from agent_actions.validation.utils.agent_config_validation_utilities import (
    AgentConfigValidationUtilities
)


class AgentRequiredFieldsValidator(BaseAgentEntryValidator):
    """
    Validates that all required agent fields are present.

    Required fields:
    - agent_type
    - model_name

    Complexity: CC ~3
    """

    def validate(self, context) -> AgentEntryValidationResult:
        """
        Check that all required fields are present in entry.

        Args:
            context: Validation context

        Returns:
            Validation result with errors for missing fields
        """
        normalized_entry = context.normalized_entry
        desc = context.description

        # Get required keys from utilities
        required_keys = AgentConfigValidationUtilities.get_required_agent_keys()

        # Find missing keys (case-insensitive check via normalized_entry)
        present_keys = set(normalized_entry.keys())
        missing_keys = required_keys - present_keys

        if missing_keys:
            sorted_missing = sorted(missing_keys)
            error_msg = (
                f"{desc} missing required key(s): "
                f"{', '.join(sorted_missing)}."
            )
            return AgentEntryValidationResult.with_errors([error_msg])

        return AgentEntryValidationResult.success()
