"""
Validator for agent type and type-specific configuration requirements.

Different agent types have different required fields:
- llm: requires model_name
- function: requires code_path (and validates it exists)
- tool: requires model_name
"""

from pathlib import Path
from agent_actions.validation.validators.base_agent_validator import (
    BaseAgentEntryValidator,
    AgentEntryValidationResult
)
from agent_actions.validation.utils.agent_config_validation_utilities import (
    AgentConfigValidationUtilities
)
from agent_actions.validation.base_validator import BaseValidator


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
        entry = context.entry
        normalized_entry = context.normalized_entry
        desc = context.description
        proj_root = context.project_root

        errors = []

        # 1. Validate 'name' field type if present
        name = normalized_entry.get('name')
        if 'name' in normalized_entry and not isinstance(name, str):
            errors.append(f"{desc} 'name' must be string.")

        # 2. Validate 'agent_type' field
        if 'agent_type' in normalized_entry:
            # Check if agent_type is a string (use original entry for exact type check)
            agent_type_value = AgentConfigValidationUtilities.get_case_insensitive_value(
                entry, 'agent_type'
            )

            if not isinstance(agent_type_value, str):
                errors.append(f"{desc} 'agent_type' must be string.")
            else:
                # Normalize for comparison
                agent_type = str(agent_type_value).lower()

                # 3. Check type-specific required keys
                type_specific_keys = AgentConfigValidationUtilities.get_agent_type_specific_keys(
                    agent_type
                )

                if type_specific_keys:
                    missing_type_keys = {
                        k for k in type_specific_keys
                        if k not in normalized_entry
                    }

                    if missing_type_keys:
                        sorted_missing = sorted(missing_type_keys)
                        errors.append(
                            f"{desc} (type '{agent_type}') missing type‑specific "
                            f"key(s): {', '.join(sorted_missing)}."
                        )

                # 4. Special validation for 'function' agent type
                if agent_type == 'function' and 'code_path' in normalized_entry:
                    code_path_value = normalized_entry['code_path']

                    if not isinstance(code_path_value, str):
                        errors.append(
                            f"{desc} 'code_path' for function agent must be a string."
                        )
                    elif proj_root and not code_path_value.startswith(('http://', 'https://')):
                        # Resolve path (absolute or relative to project root)
                        code_path = Path(code_path_value)
                        abs_code_path = (
                            code_path if code_path.is_absolute()
                            else proj_root / code_path
                        )

                        # Validate path exists and is a file
                        if not BaseValidator._ensure_path_exists(abs_code_path):
                            errors.append(
                                f"{desc} 'code_path' ({abs_code_path}) does not exist."
                            )
                        elif not BaseValidator._is_file(abs_code_path):
                            errors.append(
                                f"{desc} 'code_path' ({abs_code_path}) is not a file."
                            )

        if errors:
            return AgentEntryValidationResult.with_errors(errors)

        return AgentEntryValidationResult.success()
