"""
Detector for unknown/unexpected keys in agent configuration.

Issues warnings (not errors) for keys that are not recognized,
which may indicate typos or deprecated fields.
"""

from agent_actions.validation.agent_validators.base_agent_validator import (
    BaseAgentEntryValidator,
    AgentEntryValidationResult,
)
from agent_actions.validation.utils.agent_config_validation_utilities import (
    AgentConfigValidationUtilities,
)


class UnknownKeysDetector(BaseAgentEntryValidator):
    """
    Detects unknown or unexpected keys in agent configuration.

    This validator issues WARNINGS (not errors) for keys that aren't
    in the known required/optional/type-specific sets.

    Helps catch:
    - Typos (e.g., 'dependecies' instead of 'dependencies')
    - Deprecated fields
    - Configuration mistakes

    Complexity: CC ~3
    """

    def validate(self, context) -> AgentEntryValidationResult:
        """
        Detect unknown keys in agent configuration.

        Args:
            context: Validation context

        Returns:
            Validation result with warnings for unknown keys
        """
        entry = context.entry
        normalized_entry = context.normalized_entry
        desc = context.description

        # Get agent_type to include type-specific keys
        agent_type = str(normalized_entry.get("agent_type", "")).lower()

        # Build set of all known keys
        all_known_keys = AgentConfigValidationUtilities.get_all_known_agent_keys(agent_type)

        # Get keys from entry (exclude 'config' key from check)
        keys_to_check = {k.lower() for k in entry.keys() if k.lower() != "config"}

        # Find unknown keys
        unknown_keys = keys_to_check - all_known_keys

        if unknown_keys:
            sorted_unknown = sorted(unknown_keys)
            warning_msg = (
                f"{desc} has unknown key(s): {', '.join(sorted_unknown)}. "
                f"Ensure these are intended or correct typos."
            )
            return AgentEntryValidationResult.with_warnings([warning_msg])

        return AgentEntryValidationResult.success()
