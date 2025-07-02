import os

from agent_actions.config_keys import API_KEY_KEY, JSON_MODE_KEY
class BaseVendorHandler:
    """Common functionality shared by vendor handlers."""

    @staticmethod
    def get_api_key(agent_config):
        """Return the API key using the name specified in ``agent_config``."""
        key_name = agent_config.get(API_KEY_KEY)
        return os.getenv(key_name) if key_name else None

    @classmethod
    def invoke(cls, agent_config, prompt_config, context_data, schema):
        """Dispatch to JSON or non-JSON methods after loading the API key."""
        api_key = cls.get_api_key(agent_config)
        json_mode = agent_config.get(JSON_MODE_KEY, True)
        if json_mode:
            return cls.call_json(api_key, agent_config, prompt_config, context_data, schema)
        return cls.call_non_json(api_key, agent_config, prompt_config, context_data)
