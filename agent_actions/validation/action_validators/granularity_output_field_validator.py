"""Validator for granularity and output_field configuration."""

from agent_actions.output.response.config_fields import get_default
from agent_actions.utils.constants import (
    HITL_FILE_GRANULARITY_ERROR,
    JSON_MODE_KEY,
)
from agent_actions.validation.action_validators.base_action_validator import (
    ActionEntryValidationResult,
    BaseActionEntryValidator,
)
from agent_actions.validation.utils.action_config_validation_utilities import (
    ActionConfigValidationUtilities,
)


class GranularityAndOutputFieldValidator(BaseActionEntryValidator):
    """Validates granularity enum, output_field compatibility, and kind-granularity rules."""

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
            elif granularity == "record":
                kind = str(normalized_entry.get("kind", "")).lower()
                if kind == "hitl":
                    errors.append(f"{desc} {HITL_FILE_GRANULARITY_ERROR}")
            elif granularity == "file":
                kind = str(normalized_entry.get("kind", "")).lower()
                if kind not in ("tool", "hitl"):
                    errors.append(
                        f"{desc} FILE granularity is only supported for tool and hitl actions. "
                        "LLM actions must use RECORD granularity."
                    )

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
