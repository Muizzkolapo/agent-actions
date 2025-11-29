import os
import re
from typing import Any, Dict, Optional, Union
from agent_actions.utilities.constants import API_KEY_KEY, JSON_MODE_KEY

class BaseVendorHandler:
    """Common functionality shared by vendor handlers."""

    @staticmethod
    def redact_sensitive_data(data: Any, redact_keys: tuple = ('api_key', 'key', 'token', 'password', 'secret', 'authorization')) -> Any:
        """
        Redact sensitive data from request/response for logging.

        Args:
            data: Data to redact (dict, list, or primitive)
            redact_keys: Tuple of key names to redact

        Returns:
            Redacted copy of data
        """
        if isinstance(data, dict):
            return {
                k: '[REDACTED]' if any(key in k.lower() for key in redact_keys) else BaseVendorHandler.redact_sensitive_data(v, redact_keys)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [BaseVendorHandler.redact_sensitive_data(item, redact_keys) for item in data]
        elif isinstance(data, str):
            # Redact API key patterns (sk-*, anthropic-*, etc.)
            patterns = [
                (r'sk-[a-zA-Z0-9]{20,}', 'sk-[REDACTED]'),
                (r'anthropic-[a-zA-Z0-9-]{20,}', 'anthropic-[REDACTED]'),
                (r'AIza[a-zA-Z0-9_-]{35}', 'AIza[REDACTED]'),  # Google API keys
            ]
            result = data
            for pattern, replacement in patterns:
                result = re.sub(pattern, replacement, result)
            return result
        return data

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
        from agent_actions.shared.exceptions import ConfigurationError
        key_name: Optional[str] = agent_config.get(API_KEY_KEY)
        if not key_name:
            raise ConfigurationError('API key configuration is missing', context={'agent': agent_config.get('agent_type', 'unknown'), 'field': API_KEY_KEY, 'operation': 'get_api_key', 'hint': 'Add api_key to agent_actions.yml, workflow defaults, or action config'})
        if key_name.startswith('${') and key_name.endswith('}'):
            env_var_name = key_name[2:-1]
        else:
            env_var_name = key_name
        if env_var_name not in os.environ:
            raise ConfigurationError(f"Environment variable '{env_var_name}' is not set", context={'agent': agent_config.get('agent_type', 'unknown'), 'env_var': env_var_name, 'config_value': key_name, 'operation': 'get_api_key', 'hint': f'Set the environment variable:\n  export {env_var_name}=your-api-key'})
        api_key = os.getenv(env_var_name)
        if not api_key:
            raise ConfigurationError(f"Environment variable '{env_var_name}' is set but empty", context={'agent': agent_config.get('agent_type', 'unknown'), 'env_var': env_var_name, 'config_value': key_name, 'operation': 'get_api_key', 'hint': f'Provide a value: export {env_var_name}=your-api-key'})
        return api_key

    @classmethod
    def invoke(cls, agent_config: Dict[str, Any], prompt_config: Dict[str, Any], context_data: Dict[str, Any], schema: Optional[Dict[str, Any]]) -> Union[str, Dict[str, Any]]:
        """Dispatch to JSON or non-JSON methods after loading the API key."""
        api_key: Optional[str] = cls.get_api_key(agent_config)
        json_mode: bool = agent_config.get(JSON_MODE_KEY, True)
        if json_mode:
            return cls.call_json(api_key, agent_config, prompt_config, context_data, schema)
        return cls.call_non_json(api_key, agent_config, prompt_config, context_data)