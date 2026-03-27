"""Validator for action entry basic structure."""

from agent_actions.validation.action_validators.base_action_validator import (
    ActionEntryValidationResult,
    BaseActionEntryValidator,
)


class ActionEntryStructureValidator(BaseActionEntryValidator):
    """Validates that the action entry is a dictionary (must run first in chain)."""

    def validate(self, context) -> ActionEntryValidationResult:
        """Return critical failure if entry is not a dict."""
        entry = context.entry
        desc = context.description

        if not isinstance(entry, dict):
            error_msg = f"{desc} is not a dictionary."
            return ActionEntryValidationResult.critical_failure(error_msg)

        return ActionEntryValidationResult.success()
