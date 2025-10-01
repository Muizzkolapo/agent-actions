import os
from typing import Any, Dict, Optional, Union

from agent_actions.core.constants import API_KEY_KEY, JSON_MODE_KEY

class BaseVendorHandler:
    """Common functionality shared by vendor handlers."""

    @staticmethod
    def get_api_key(agent_config: Dict[str, Any]) -> Optional[str]:
        """
        Return the API key using the name specified in ``agent_config``.

        Supports two formats:
        1. Environment variable interpolation: ${VAR_NAME}
        2. Direct environment variable name: VAR_NAME (legacy)

        Args:
            agent_config: Agent configuration dict containing api_key field

        Returns:
            The API key value from environment

        Raises:
            ConfigurationError: If api_key is not configured or environment variable doesn't exist
        """
        from agent_actions.core.exceptions import ConfigurationError

        key_name: Optional[str] = agent_config.get(API_KEY_KEY)

        if not key_name:
            raise ConfigurationError(
                "API key configuration is missing",
                context={
                    'agent': agent_config.get('agent_type', 'unknown'),
                    'field': API_KEY_KEY,
                    'operation': 'get_api_key',
                    'hint': 'Add api_key to agent_actions.yml, workflow defaults, or action config'
                }
            )

        # Parse environment variable reference
        # Support both ${VAR} format and direct VAR format (legacy)
        if key_name.startswith('${') and key_name.endswith('}'):
            # New format: ${ANTHROPIC_API_KEY}
            env_var_name = key_name[2:-1]  # Extract variable name
        else:
            # Legacy format: ANTHROPIC_API_KEY (direct env var name)
            env_var_name = key_name

        # Check if variable EXISTS in environment (not just if it's empty)
        if env_var_name not in os.environ:
            raise ConfigurationError(
                f"Environment variable '{env_var_name}' is not set",
                context={
                    'agent': agent_config.get('agent_type', 'unknown'),
                    'env_var': env_var_name,
                    'config_value': key_name,  # Shows ${VAR} or VAR
                    'operation': 'get_api_key',
                    'hint': f'Set the environment variable:\n  export {env_var_name}=your-api-key'
                }
            )

        # Now we know it exists, get the value
        api_key = os.getenv(env_var_name)

        # Check if value is empty string (less common but possible)
        if not api_key:
            raise ConfigurationError(
                f"Environment variable '{env_var_name}' is set but empty",
                context={
                    'agent': agent_config.get('agent_type', 'unknown'),
                    'env_var': env_var_name,
                    'config_value': key_name,
                    'operation': 'get_api_key',
                    'hint': f'Provide a value: export {env_var_name}=your-api-key'
                }
            )

        return api_key

    @classmethod
    def invoke(cls, agent_config: Dict[str, Any], prompt_config: Dict[str, Any], 
              context_data: Dict[str, Any], schema: Optional[Dict[str, Any]]) -> Union[str, Dict[str, Any]]:
        """Dispatch to JSON or non-JSON methods after loading the API key."""
        api_key: Optional[str] = cls.get_api_key(agent_config)
        json_mode: bool = agent_config.get(JSON_MODE_KEY, True)
        if json_mode:
            return cls.call_json(api_key, agent_config, prompt_config, context_data, schema)
        return cls.call_non_json(api_key, agent_config, prompt_config, context_data)
