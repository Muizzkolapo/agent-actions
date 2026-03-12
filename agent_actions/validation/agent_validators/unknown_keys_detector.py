"""Detector for unknown/unexpected keys in agent configuration."""

from agent_actions.validation.agent_validators.base_agent_validator import (
    BaseAgentEntryValidator,
    AgentEntryValidationResult,
)
from agent_actions.validation.utils.agent_config_validation_utilities import (
    AgentConfigValidationUtilities,
)


class UnknownKeysDetector(BaseAgentEntryValidator):
    """Detects unknown keys in agent configuration and issues warnings."""

    def validate(self, context) -> AgentEntryValidationResult:
        """Detect unknown keys in agent configuration."""
        entry = context.entry
        normalized_entry = context.normalized_entry
        desc = context.description

        agent_type = str(normalized_entry.get("agent_type", "")).lower()
        all_known_keys = AgentConfigValidationUtilities.get_all_known_agent_keys(agent_type)
        keys_to_check = {k.lower() for k in entry.keys() if k.lower() != "config"}
        unknown_keys = keys_to_check - all_known_keys

        if unknown_keys:
            sorted_unknown = sorted(unknown_keys)
            warning_msg = (
                f"{desc} has unknown key(s): {', '.join(sorted_unknown)}. "
                f"Ensure these are intended or correct typos."
            )
            return AgentEntryValidationResult.with_warnings([warning_msg])

        return AgentEntryValidationResult.success()
