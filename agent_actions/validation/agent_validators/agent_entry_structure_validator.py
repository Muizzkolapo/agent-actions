"""Validator for agent entry basic structure."""

from agent_actions.validation.agent_validators.base_agent_validator import (
    BaseAgentEntryValidator,
    AgentEntryValidationResult,
)


class AgentEntryStructureValidator(BaseAgentEntryValidator):
    """Validates that the agent entry is a dictionary (must run first in chain)."""

    def validate(self, context) -> AgentEntryValidationResult:
        """Return critical failure if entry is not a dict."""
        entry = context.entry
        desc = context.description

        if not isinstance(entry, dict):
            error_msg = f"{desc} is not a dictionary."
            return AgentEntryValidationResult.critical_failure(error_msg)

        return AgentEntryValidationResult.success()
