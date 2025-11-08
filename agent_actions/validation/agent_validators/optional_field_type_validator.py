"""
Validator for optional field types in agent configuration.

Validates that optional fields have correct types when present:
- description: string
- version: string, int, or float
- dependencies: list
- is_operational: boolean
- json_mode: boolean
- prompt_debug: boolean
"""

from agent_actions.validation.agent_validators.base_agent_validator import (
    BaseAgentEntryValidator,
    AgentEntryValidationResult
)
from agent_actions.utilities.constants import JSON_MODE_KEY


class OptionalFieldTypeValidator(BaseAgentEntryValidator):
    """
    Validates types of optional configuration fields.

    This validator checks that when optional fields are present,
    they have the correct data types.

    Complexity: CC ~7 (one check per optional field)
    """

    def validate(self, context) -> AgentEntryValidationResult:
        """
        Validate optional field types.

        Args:
            context: Validation context

        Returns:
            Validation result with type errors
        """
        normalized_entry = context.normalized_entry
        desc = context.description

        errors = []

        # Check 'description' field type
        if 'description' in normalized_entry:
            if not isinstance(normalized_entry['description'], str):
                errors.append(f"{desc} 'description' should be a string.")

        # Check 'version' field type
        if 'version' in normalized_entry:
            if not isinstance(normalized_entry['version'], (str, int, float)):
                errors.append(f"{desc} 'version' should be a string or number.")

        # Check 'dependencies' field type
        if 'dependencies' in normalized_entry:
            if not isinstance(normalized_entry['dependencies'], list):
                errors.append(f"{desc} 'dependencies' should be a list.")

        # Check 'is_operational' field type
        if 'is_operational' in normalized_entry:
            if not isinstance(normalized_entry['is_operational'], bool):
                errors.append(f"{desc} 'is_operational' should be a boolean.")

        # Check 'json_mode' field type
        if JSON_MODE_KEY in normalized_entry:
            if not isinstance(normalized_entry[JSON_MODE_KEY], bool):
                errors.append(f"{desc} 'json_mode' should be a boolean.")

        # Check 'prompt_debug' field type
        if 'prompt_debug' in normalized_entry:
            if not isinstance(normalized_entry['prompt_debug'], bool):
                errors.append(f"{desc} 'prompt_debug' should be a boolean.")

        if errors:
            return AgentEntryValidationResult.with_errors(errors)

        return AgentEntryValidationResult.success()
