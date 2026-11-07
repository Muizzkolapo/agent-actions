"""Validator for granularity and output_field configuration."""

from agent_actions.output.response.config_fields import get_default
from agent_actions.utils.constants import JSON_MODE_KEY
from agent_actions.validation.action_validators.base_action_validator import (
    ActionEntryValidationResult,
    BaseActionEntryValidator,
)
from agent_actions.validation.utils.action_config_validation_utilities import (
    ActionConfigValidationUtilities,
)


class GranularityAndOutputFieldValidator(BaseActionEntryValidator):
    """Validates the granularity value and output_field compatibility.

    Which kinds may run at which granularity is decided by the expander, which both
    `agac inspect` and `agac run` go through and which sees inherited defaults.
    """

    def validate(self, context) -> ActionEntryValidationResult:
        """Validate granularity and output_field configuration."""
        normalized_entry = context.normalized_entry
        desc = context.description

        errors = []

        if "granularity" in normalized_entry:
            granularity_raw = normalized_entry.get("granularity", get_default("granularity"))
            granularity = str(granularity_raw).lower()

            valid_granularity_values = (
                ActionConfigValidationUtilities.get_valid_granularity_values()
            )

            if granularity not in valid_granularity_values:
                valid_values_str = "' or '".join(sorted(valid_granularity_values))
                errors.append(f"{desc} 'granularity' must be '{valid_values_str}'.")

        if "output_field" in normalized_entry:
            json_mode = normalized_entry.get(JSON_MODE_KEY, True)

            if json_mode:
                errors.append(
                    f"{desc} 'output_field' requires 'json_mode: false'. "
                    f"Add 'json_mode: false' to this action's config."
                )

        if errors:
            return ActionEntryValidationResult(errors=errors)

        return ActionEntryValidationResult.success()
