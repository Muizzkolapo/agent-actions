"""Validator for agent type and type-specific configuration requirements."""

from pathlib import Path

from agent_actions.utils.constants import RESERVED_AGENT_NAMES
from agent_actions.validation.action_validators.base_action_validator import (
    ActionEntryValidationResult,
    BaseActionEntryValidator,
)
from agent_actions.validation.utils.action_config_validation_utilities import (
    ActionConfigValidationUtilities,
)


class ActionTypeSpecificValidator(BaseActionEntryValidator):
    """Validates agent type field and type-specific requirements."""

    def validate(self, context) -> ActionEntryValidationResult:
        """Validate agent type and type-specific requirements."""
        errors: list[str] = []

        self._validate_name_field(context, errors)
        self._validate_agent_type_field(context, errors)

        if errors:
            return ActionEntryValidationResult.with_errors(errors)

        return ActionEntryValidationResult.success()

    def _validate_name_field(self, context, errors: list) -> None:
        """Validate the 'name' field type."""
        name = context.normalized_entry.get("name")
        if "name" in context.normalized_entry and not isinstance(name, str):
            errors.append(f"{context.description} 'name' must be string.")
            return

        if isinstance(name, str):
            normalized = name.strip().lower()
            if normalized in RESERVED_AGENT_NAMES:
                errors.append(f"{context.description} 'name' uses reserved namespace '{name}'.")

    def _validate_agent_type_field(self, context, errors: list) -> None:
        """Validate agent_type field and type-specific requirements."""
        if "agent_type" not in context.normalized_entry:
            return

        agent_type_value = ActionConfigValidationUtilities.get_case_insensitive_value(
            context.entry, "agent_type"
        )

        if not isinstance(agent_type_value, str):
            errors.append(f"{context.description} 'agent_type' must be string.")
            return

        agent_type = str(agent_type_value).lower()

        self._validate_type_specific_keys(context, agent_type, errors)

        if agent_type == "function":
            self._validate_function_agent_code_path(context, errors)

    def _validate_type_specific_keys(self, context, agent_type: str, errors: list) -> None:
        """Validate type-specific required keys are present."""
        type_specific_keys = ActionConfigValidationUtilities.get_action_type_specific_keys(agent_type)

        if not type_specific_keys:
            return

        missing_type_keys = {k for k in type_specific_keys if k not in context.normalized_entry}

        if missing_type_keys:
            sorted_missing = sorted(missing_type_keys)
            errors.append(
                f"{context.description} (type '{agent_type}') missing type‑specific "
                f"key(s): {', '.join(sorted_missing)}."
            )

    def _validate_function_agent_code_path(self, context, errors: list) -> None:
        """Validate code_path for function agent type."""
        if "code_path" not in context.normalized_entry:
            return

        code_path_value = context.normalized_entry["code_path"]

        if not isinstance(code_path_value, str):
            errors.append(f"{context.description} 'code_path' for function agent must be a string.")
            return

        if not context.project_root:
            return

        if code_path_value.startswith(("http://", "https://")):
            return

        code_path = Path(code_path_value)
        abs_code_path = code_path if code_path.is_absolute() else context.project_root / code_path

        if not abs_code_path.exists():
            errors.append(f"{context.description} 'code_path' ({abs_code_path}) does not exist.")
        elif not abs_code_path.is_file():
            errors.append(f"{context.description} 'code_path' ({abs_code_path}) is not a file.")
