"""
Validator for agent type and type-specific configuration requirements.

Different agent types have different required fields:
- llm: requires model_name
- function: requires code_path (and validates it exists)
- tool: requires model_name
"""

from pathlib import Path
from agent_actions.validation.agent_validators.base_agent_validator import (
    BaseAgentEntryValidator,
    AgentEntryValidationResult,
)
from agent_actions.validation.utils.agent_config_validation_utilities import (
    AgentConfigValidationUtilities,
)


class AgentTypeSpecificValidator(BaseAgentEntryValidator):
    """
    Validates agent type field and type-specific requirements.

    Checks:
    1. name field is string
    2. agent_type field is string
    3. Type-specific required fields are present
    4. For function agents: code_path exists and is a file

    Complexity: CC ~8
    """

    def validate(self, context) -> AgentEntryValidationResult:
        """
        Validate agent type and type-specific requirements.

        Args:
            context: Validation context

        Returns:
            Validation result with any errors found
        """
        errors = []

        # 1. Validate 'name' field type if present
        self._validate_name_field(context, errors)

        # 2. Validate 'agent_type' field and type-specific requirements
        self._validate_agent_type_field(context, errors)

        if errors:
            return AgentEntryValidationResult.with_errors(errors)

        return AgentEntryValidationResult.success()

    def _validate_name_field(self, context, errors: list) -> None:
        """Validate the 'name' field type."""
        name = context.normalized_entry.get("name")
        if "name" in context.normalized_entry and not isinstance(name, str):
            errors.append(f"{context.description} 'name' must be string.")

    def _validate_agent_type_field(self, context, errors: list) -> None:
        """Validate agent_type field and type-specific requirements."""
        if "agent_type" not in context.normalized_entry:
            return

        agent_type_value = AgentConfigValidationUtilities.get_case_insensitive_value(
            context.entry, "agent_type"
        )

        if not isinstance(agent_type_value, str):
            errors.append(f"{context.description} 'agent_type' must be string.")
            return

        agent_type = str(agent_type_value).lower()

        # Check type-specific required keys
        self._validate_type_specific_keys(context, agent_type, errors)

        # Special validation for 'function' agent type
        if agent_type == "function":
            self._validate_function_agent_code_path(context, errors)

    def _validate_type_specific_keys(self, context, agent_type: str, errors: list) -> None:
        """Validate type-specific required keys are present."""
        type_specific_keys = AgentConfigValidationUtilities.get_agent_type_specific_keys(agent_type)

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

        # Resolve and validate file path
        code_path = Path(code_path_value)
        abs_code_path = code_path if code_path.is_absolute() else context.project_root / code_path

        if not abs_code_path.exists():
            errors.append(f"{context.description} 'code_path' ({abs_code_path}) does not exist.")
        elif not abs_code_path.is_file():
            errors.append(f"{context.description} 'code_path' ({abs_code_path}) is not a file.")
