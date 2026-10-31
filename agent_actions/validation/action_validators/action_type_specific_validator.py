"""Validator for an action entry's name and agent_type fields."""

from agent_actions.utils.constants import RESERVED_AGENT_NAMES
from agent_actions.validation.action_validators.base_action_validator import (
    ActionEntryValidationResult,
    BaseActionEntryValidator,
)
from agent_actions.validation.utils.action_config_validation_utilities import (
    ActionConfigValidationUtilities,
)


class ActionTypeSpecificValidator(BaseActionEntryValidator):
    """Validates the name and agent_type fields.

    agent_type holds the action's name, not its type; the type is ``kind``.
    """

    def validate(self, context) -> ActionEntryValidationResult:
        errors: list[str] = []

        self._validate_name_field(context, errors)
        self._validate_agent_type_field(context, errors)

        if errors:
            return ActionEntryValidationResult.with_errors(errors)

        return ActionEntryValidationResult.success()

    def _validate_name_field(self, context, errors: list) -> None:
        name = context.normalized_entry.get("name")
        if "name" in context.normalized_entry and not isinstance(name, str):
            errors.append(f"{context.description} 'name' must be string.")
            return

        if isinstance(name, str):
            normalized = name.strip().lower()
            if normalized in RESERVED_AGENT_NAMES:
                errors.append(f"{context.description} 'name' uses reserved namespace '{name}'.")

    def _validate_agent_type_field(self, context, errors: list) -> None:
        if "agent_type" not in context.normalized_entry:
            return

        agent_type_value = ActionConfigValidationUtilities.get_case_insensitive_value(
            context.entry, "agent_type"
        )

        if not isinstance(agent_type_value, str):
            errors.append(f"{context.description} 'agent_type' must be string.")
