"""
Validator for granularity and output_field configuration.

Checks:
- granularity must be 'record' or 'file'
- output_field can only be used when json_mode is false
"""

from agent_actions.validation.agent_validators.base_agent_validator import (
    BaseAgentEntryValidator,
    AgentEntryValidationResult,
)
from agent_actions.validation.utils.agent_config_validation_utilities import (
    AgentConfigValidationUtilities,
)
from agent_actions.utilities.constants import JSON_MODE_KEY


class GranularityAndOutputFieldValidator(BaseAgentEntryValidator):
    """
    Validates granularity enum and output_field compatibility.

    Rules:
    1. granularity must be 'record' or 'file' if present
    2. output_field requires json_mode=false

    Complexity: CC ~3
    """

    def validate(self, context) -> AgentEntryValidationResult:
        """
        Validate granularity and output_field configuration.

        Args:
            context: Validation context

        Returns:
            Validation result with errors
        """
        normalized_entry = context.normalized_entry
        desc = context.description

        errors = []

        # Check granularity enum value
        if "granularity" in normalized_entry:
            granularity_raw = normalized_entry.get("granularity", "record")
            granularity = str(granularity_raw).lower()

            valid_granularity_values = AgentConfigValidationUtilities.get_valid_granularity_values()

            if granularity not in valid_granularity_values:
                valid_values_str = "' or '".join(sorted(valid_granularity_values))
                errors.append(f"{desc} 'granularity' must be '{valid_values_str}'.")

        # Check output_field compatibility with json_mode
        if "output_field" in normalized_entry:
            # output_field can only be used when json_mode is false
            json_mode = normalized_entry.get(JSON_MODE_KEY, True)

            if json_mode:
                errors.append(f"{desc} 'output_field' can only be used when 'json_mode' is false.")

        if errors:
            return AgentEntryValidationResult.with_errors(errors)

        return AgentEntryValidationResult.success()
