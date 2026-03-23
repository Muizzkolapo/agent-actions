"""
Shared utilities for action configuration validation.
"""

from typing import Any

from agent_actions.utils.constants import (
    API_KEY_KEY,
    CHUNK_CONFIG_KEY,
    DEFAULT_ACTION_KIND,
    JSON_MODE_KEY,
    MODEL_NAME_KEY,
    MODEL_VENDOR_KEY,
    PROMPT_KEY,
    SCHEMA_KEY,
    SCHEMA_NAME_KEY,
)


class ActionConfigValidationUtilities:
    """
    Centralized utilities for action configuration validation.

    This class consolidates all shared logic that was scattered across
    the original ConfigValidator class.
    """

    # ===== Configuration Constants =====

    _REQUIRED_ACTION_KEYS: set[str] = {
        "agent_type",
        MODEL_NAME_KEY,  # 'model_name'
    }

    _OPTIONAL_ACTION_KEYS: set[str] = {
        "name",
        "description",
        "version",
        "author",
        "dependencies",
        "imports",
        "config",
        "granularity",
        "run_mode",
        MODEL_VENDOR_KEY,
        JSON_MODE_KEY,
        "prompt_debug",
        API_KEY_KEY,
        PROMPT_KEY,
        SCHEMA_NAME_KEY,
        SCHEMA_KEY,
        "tools",
        CHUNK_CONFIG_KEY,
        "conditional_clause",
        "is_operational",
        "ephemeral",
        "enabled",
        "add_dispatch",
        "output_field",
        "context_scope",
        "reprompt",
        "constraints",
        "kind",
        "impl",
        "intent",
        "guard",
        "versions",
        "version_consumption",
        "retry",
    }

    _ACTION_TYPE_SPECIFIC_KEYS: dict[str, set[str]] = {
        DEFAULT_ACTION_KIND: {MODEL_NAME_KEY},
        "function": {"code_path"},
        "tool": {MODEL_NAME_KEY},
    }

    _VALID_BATCH_VENDORS: set[str] = {"openai", "gemini", "anthropic", "groq", "mistral"}

    _VALID_GRANULARITY_VALUES: set[str] = {"record", "file"}

    # ===== Case-Insensitive Dict Operations =====

    @staticmethod
    def normalize_entry_keys_to_lowercase(entry: dict[str, Any]) -> dict[str, Any]:
        """
        Convert all dictionary keys to lowercase for case-insensitive comparison.

        Args:
            entry: Original dictionary with mixed-case keys

        Returns:
            New dictionary with all keys converted to lowercase

        Example:
            >>> normalize_entry_keys_to_lowercase({'AgentType': 'llm', 'Name': 'test'})
            {'agenttype': 'llm', 'name': 'test'}
        """
        return {str(k).lower(): v for k, v in entry.items()}

    @staticmethod
    def get_case_insensitive_value(entry: dict[str, Any], key: str, default: Any = None) -> Any:
        """
        Get value from dict using case-insensitive key lookup.

        Args:
            entry: Dictionary to search
            key: Key to find (case-insensitive)
            default: Value to return if key not found

        Returns:
            Value for the key (case-insensitive match) or default

        Example:
            >>> get_case_insensitive_value({'AgentType': 'llm'}, 'agent_type')
            'llm'
        """
        for k, v in entry.items():
            if str(k).lower() == key.lower():
                return v
        return default

    # ===== Context & Error Formatting =====

    @staticmethod
    def format_validation_context(entry: dict[str, Any], context_name: str) -> str:
        """
        Format a standardized description for error messages.

        Args:
            entry: Action configuration entry
            context_name: Context name (agent file name, etc.)

        Returns:
            Formatted description string

        Example:
            "agent entry llm in 'my_agent'"
        """
        # Try to get agent_type from entry (case-insensitive)
        agent_type = ActionConfigValidationUtilities.get_case_insensitive_value(
            entry, "agent_type", "unknown"
        )

        return f"agent entry {agent_type} in '{context_name}'"

    # ===== Configuration Accessors =====

    @staticmethod
    def get_required_action_keys() -> set[str]:
        """Get set of required action configuration keys."""
        return ActionConfigValidationUtilities._REQUIRED_ACTION_KEYS.copy()

    @staticmethod
    def get_optional_action_keys() -> set[str]:
        """Get set of optional action configuration keys."""
        return ActionConfigValidationUtilities._OPTIONAL_ACTION_KEYS.copy()

    @staticmethod
    def get_action_type_specific_keys(agent_type: str) -> set[str]:
        """
        Get required keys for a specific agent type.

        Args:
            agent_type: Type of agent ('llm', 'function', 'tool')

        Returns:
            Set of required keys for that type, or empty set if no special requirements
        """
        return ActionConfigValidationUtilities._ACTION_TYPE_SPECIFIC_KEYS.get(
            agent_type.lower(), set()
        ).copy()

    @staticmethod
    def get_all_known_action_keys(agent_type: str | None = None) -> set[str]:
        """
        Get all known action keys (required + optional + type-specific).

        Args:
            agent_type: Optional agent type to include type-specific keys

        Returns:
            Set of all known keys
        """
        all_keys = (
            ActionConfigValidationUtilities._REQUIRED_ACTION_KEYS
            | ActionConfigValidationUtilities._OPTIONAL_ACTION_KEYS
        )

        if agent_type:
            type_keys = ActionConfigValidationUtilities.get_action_type_specific_keys(agent_type)
            all_keys = all_keys | type_keys

        return all_keys

    @staticmethod
    def get_valid_batch_vendors() -> set[str]:
        """Get set of valid batch processing vendors."""
        return ActionConfigValidationUtilities._VALID_BATCH_VENDORS.copy()

    @staticmethod
    def get_valid_granularity_values() -> set[str]:
        """Get set of valid granularity values."""
        return ActionConfigValidationUtilities._VALID_GRANULARITY_VALUES.copy()
