"""
Shared utilities for agent configuration validation.

Provides:
- Case-insensitive dict operations
- Validation constants (required/optional keys)
- Error message formatting
- Agent type definitions
"""

from typing import Dict, Any, Set, Optional
from agent_actions.utilities.constants import (
    MODEL_VENDOR_KEY,
    MODEL_NAME_KEY,
    JSON_MODE_KEY,
    API_KEY_KEY,
    PROMPT_KEY,
    SCHEMA_NAME_KEY,
    SCHEMA_KEY,
    CHUNK_CONFIG_KEY
)


class AgentConfigValidationUtilities:
    """
    Centralized utilities for agent configuration validation.

    This class consolidates all shared logic that was scattered across
    the original ConfigValidator class.
    """

    # ===== Configuration Constants =====

    _REQUIRED_AGENT_KEYS: Set[str] = {
        'agent_type',
        MODEL_NAME_KEY  # 'model_name'
    }

    _OPTIONAL_AGENT_KEYS: Set[str] = {
        'description', 'version', 'author', 'dependencies', 'imports',
        'config', 'granularity', MODEL_VENDOR_KEY, JSON_MODE_KEY,
        'prompt_debug', API_KEY_KEY, PROMPT_KEY, SCHEMA_NAME_KEY,
        SCHEMA_KEY, 'tools', CHUNK_CONFIG_KEY, 'few_shot',
        'conditional_clause', 'is_operational', 'ephemeral',
        'add_dispatch', 'output_field', 'context_scope',
        'reprompt', 'constraints'
    }

    _AGENT_TYPE_SPECIFIC_KEYS: Dict[str, Set[str]] = {
        'llm': {MODEL_NAME_KEY},
        'function': {'code_path'},
        'tool': {MODEL_NAME_KEY}
    }

    _VALID_BATCH_VENDORS: Set[str] = {
        'openai', 'gemini', 'anthropic'
    }

    _VALID_GRANULARITY_VALUES: Set[str] = {
        'record', 'file'
    }

    # ===== Case-Insensitive Dict Operations =====

    @staticmethod
    def normalize_entry_keys_to_lowercase(entry: Dict[str, Any]) -> Dict[str, Any]:
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
    def get_case_insensitive_value(
        entry: Dict[str, Any],
        key: str,
        default: Any = None
    ) -> Any:
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
    def format_validation_context(entry: Dict[str, Any], context_name: str) -> str:
        """
        Format a standardized description for error messages.

        Args:
            entry: Agent configuration entry
            context_name: Context name (agent file name, etc.)

        Returns:
            Formatted description string

        Example:
            "agent entry llm in 'my_agent'"
        """
        # Try to get agent_type from entry (case-insensitive)
        agent_type = AgentConfigValidationUtilities.get_case_insensitive_value(
            entry, 'agent_type', 'unknown'
        )

        return f"agent entry {agent_type} in '{context_name}'"

    # ===== Configuration Accessors =====

    @staticmethod
    def get_required_agent_keys() -> Set[str]:
        """Get set of required agent configuration keys."""
        return AgentConfigValidationUtilities._REQUIRED_AGENT_KEYS.copy()

    @staticmethod
    def get_optional_agent_keys() -> Set[str]:
        """Get set of optional agent configuration keys."""
        return AgentConfigValidationUtilities._OPTIONAL_AGENT_KEYS.copy()

    @staticmethod
    def get_agent_type_specific_keys(agent_type: str) -> Set[str]:
        """
        Get required keys for a specific agent type.

        Args:
            agent_type: Type of agent ('llm', 'function', 'tool')

        Returns:
            Set of required keys for that type, or empty set if no special requirements
        """
        return AgentConfigValidationUtilities._AGENT_TYPE_SPECIFIC_KEYS.get(
            agent_type.lower(), set()
        ).copy()

    @staticmethod
    def get_all_known_agent_keys(agent_type: Optional[str] = None) -> Set[str]:
        """
        Get all known agent keys (required + optional + type-specific).

        Args:
            agent_type: Optional agent type to include type-specific keys

        Returns:
            Set of all known keys
        """
        all_keys = (
            AgentConfigValidationUtilities._REQUIRED_AGENT_KEYS |
            AgentConfigValidationUtilities._OPTIONAL_AGENT_KEYS
        )

        if agent_type:
            type_keys = AgentConfigValidationUtilities.get_agent_type_specific_keys(agent_type)
            all_keys = all_keys | type_keys

        return all_keys

    @staticmethod
    def get_valid_batch_vendors() -> Set[str]:
        """Get set of valid batch processing vendors."""
        return AgentConfigValidationUtilities._VALID_BATCH_VENDORS.copy()

    @staticmethod
    def get_valid_granularity_values() -> Set[str]:
        """Get set of valid granularity values."""
        return AgentConfigValidationUtilities._VALID_GRANULARITY_VALUES.copy()
