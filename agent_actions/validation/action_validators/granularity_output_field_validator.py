"""Validator for granularity and output_field configuration."""

from agent_actions.output.response.config_fields import get_default
from agent_actions.utils.constants import (
    HITL_FILE_GRANULARITY_ERROR,
    JSON_MODE_KEY,
    SCHEMA_KEY,
    SCHEMA_NAME_KEY,
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
                errors.append(f"{desc} 'output_field' can only be used when 'json_mode' is false.")

        reprompt_raw = normalized_entry.get("reprompt")
        reprompt_cfg = reprompt_raw if isinstance(reprompt_raw, dict) else {}
        has_schema = bool(normalized_entry.get(SCHEMA_KEY) or normalized_entry.get(SCHEMA_NAME_KEY))
        schema_mismatch_mode = reprompt_cfg.get("on_schema_mismatch")
        if schema_mismatch_mode in ("reprompt", "reject") and not has_schema:
            errors.append(
                f"{desc} reprompt.on_schema_mismatch: {schema_mismatch_mode} requires "
                "a schema to validate against. Define 'schema' or 'schema_name'."
            )

        warnings = []
        if reprompt_cfg and has_schema and not schema_mismatch_mode:
            warnings.append(
                f"{desc} has 'reprompt' and 'schema' configured but no "
                "'on_schema_mismatch'. Schema validation is disabled during reprompt. "
                "Add 'on_schema_mismatch: reprompt' under 'reprompt:' to enable it."
            )

        if errors or warnings:
            return ActionEntryValidationResult(errors=errors, warnings=warnings)

        return ActionEntryValidationResult.success()
