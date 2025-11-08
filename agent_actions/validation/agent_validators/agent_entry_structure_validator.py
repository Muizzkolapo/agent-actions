"""
Validator for agent entry basic structure.

This is the first validator in the chain and performs critical checks:
- Entry must be a dictionary
- Entry must be accessible
"""

from typing import Dict, Any
from agent_actions.validation.agent_validators.base_agent_validator import (
    BaseAgentEntryValidator,
    AgentEntryValidationResult
)


class AgentEntryStructureValidator(BaseAgentEntryValidator):
    """
    Validates that agent entry has valid basic structure.

    This validator MUST run first in the chain because:
    - It checks if entry is a dict (all other validators assume this)
    - Failures here are CRITICAL and stop the validation chain

    Complexity: CC ~2
    """

    def validate(self, context) -> AgentEntryValidationResult:
        """
        Validate agent entry is a dictionary.

        Args:
            context: Validation context with entry and description

        Returns:
            Critical failure if not a dict, success otherwise
        """
        entry = context.entry
        desc = context.description

        # Critical check: entry must be a dictionary
        if not isinstance(entry, dict):
            error_msg = f"{desc} is not a dictionary."
            return AgentEntryValidationResult.critical_failure(error_msg)

        return AgentEntryValidationResult.success()
