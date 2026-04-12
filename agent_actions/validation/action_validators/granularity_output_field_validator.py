"""Validator for granularity and output_field configuration."""

from agent_actions.output.response.config_fields import get_default
from agent_actions.utils.constants import HITL_FILE_GRANULARITY_ERROR, JSON_MODE_KEY
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

        if "output_field" in normalized_entry:
            json_mode = normalized_entry.get(JSON_MODE_KEY, True)

            if json_mode:
                errors.append(f"{desc} 'output_field' can only be used when 'json_mode' is false.")

        on_mismatch = normalized_entry.get("on_schema_mismatch")
        if isinstance(on_mismatch, str) and on_mismatch.lower() in ("reject", "reprompt"):
            has_schema = bool(normalized_entry.get("schema") or normalized_entry.get("schema_name"))
            if not has_schema:
                errors.append(
                    f"{desc} 'on_schema_mismatch: {on_mismatch.lower()}' requires a schema "
                    "to validate against. Define 'schema' or 'schema_name', "
                    "or change on_schema_mismatch to 'warn'."
                )

            if on_mismatch.lower() == "reprompt":
                reprompt = normalized_entry.get("reprompt")
                if not reprompt:
                    errors.append(
                        f"{desc} 'on_schema_mismatch: reprompt' requires a 'reprompt' "
                        "configuration block. Add reprompt: {{validation: your_udf_name}} "
                        "or change on_schema_mismatch to 'warn' or 'reject'."
                    )

        if errors:
            return ActionEntryValidationResult.with_errors(errors)

        return ActionEntryValidationResult.success()
