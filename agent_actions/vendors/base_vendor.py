import os


class BaseVendorHandler:
    """Common functionality shared by vendor handlers."""

    @staticmethod
    def get_api_key(agent_config):
        """Return the API key using the name specified in ``agent_config``."""
        key_name = agent_config.get("api_key")
        return os.getenv(key_name) if key_name else None

    @classmethod
    def invoke(cls, agent_config, prompt_config, context_data, schema):
        """Dispatch to JSON or non-JSON methods based on ``json_mode``."""
        json_mode = agent_config.get("json_mode", True)
        if json_mode:
            return cls.call_json(agent_config, prompt_config, context_data, schema)
        return cls.call_non_json(agent_config, prompt_config, context_data)
