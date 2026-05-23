"""Detector for unknown/unexpected keys in action configuration."""

import difflib

from agent_actions.validation.action_validators.base_action_validator import (
    ActionEntryValidationResult,
    BaseActionEntryValidator,
)
from agent_actions.validation.utils.action_config_validation_utilities import (
    ActionConfigValidationUtilities,
)


class UnknownKeysDetector(BaseActionEntryValidator):
    """Detects unknown keys in action configuration and issues warnings."""

    def validate(self, context) -> ActionEntryValidationResult:
        """Detect unknown keys in action configuration."""
        entry = context.entry
        normalized_entry = context.normalized_entry
        desc = context.description

        agent_type = str(normalized_entry.get("agent_type", "")).lower()
        all_known_keys = ActionConfigValidationUtilities.get_all_known_action_keys(agent_type)
        keys_to_check = {k.lower() for k in entry.keys() if k.lower() != "config"}
        unknown_keys = keys_to_check - all_known_keys

        if unknown_keys:
            sorted_unknown = sorted(unknown_keys)
            all_known_list = sorted(all_known_keys)
            suggestions = {}
            for key in sorted_unknown:
                matches = difflib.get_close_matches(key, all_known_list, n=1, cutoff=0.6)
                if matches:
                    suggestions[key] = matches[0]

            hint = ""
            if suggestions:
                hint = (
                    " Did you mean: "
                    + ", ".join(f"{k} -> {v}" for k, v in suggestions.items())
                    + "?"
                )

            warning_msg = (
                f"{desc} has unknown key(s): {', '.join(sorted_unknown)}.{hint} "
                f"Ensure these are intended or correct typos."
            )
            return ActionEntryValidationResult.with_warnings([warning_msg])

        return ActionEntryValidationResult.success()
