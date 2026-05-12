"""Validator that warns when schema reprompt is silently disabled."""

from agent_actions.utils.constants import SCHEMA_KEY, SCHEMA_NAME_KEY
from agent_actions.validation.action_validators.base_action_validator import (
    ActionEntryValidationResult,
    BaseActionEntryValidator,
)


class SchemaRepromptValidator(BaseActionEntryValidator):
    """Warns when an action has reprompt + schema but no on_schema_mismatch.

    Without ``on_schema_mismatch: reprompt`` (or ``reject``), schema validation
    is silently disabled even when both ``reprompt`` and ``schema`` are
    configured.  This validator surfaces that gap as an informational warning.
    """

    def validate(self, context) -> ActionEntryValidationResult:
        """Check for silently disabled schema reprompt."""
        entry = context.normalized_entry
        desc = context.description

        reprompt_raw = entry.get("reprompt")
        if not isinstance(reprompt_raw, dict):
            return ActionEntryValidationResult.success()

        has_schema = bool(entry.get(SCHEMA_KEY) or entry.get(SCHEMA_NAME_KEY))
        if not has_schema:
            return ActionEntryValidationResult.success()

        schema_mismatch_mode = reprompt_raw.get("on_schema_mismatch")
        if schema_mismatch_mode:
            return ActionEntryValidationResult.success()

        warnings = [
            f"{desc} has 'reprompt' and 'schema' configured but no "
            "'on_schema_mismatch'. Schema validation is disabled during reprompt. "
            "Add 'on_schema_mismatch: reprompt' under 'reprompt:' to enable it."
        ]

        return ActionEntryValidationResult.with_warnings(warnings)
