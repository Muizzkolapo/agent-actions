"""
Base client for agent-actions LLM invocation.

Provides common functionality for all LLM clients including API key management,
data redaction, and invocation dispatch to JSON or non-JSON modes.
"""

import logging
import os
import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from agent_actions.utils.constants import API_KEY_KEY, JSON_MODE_KEY

logger = logging.getLogger(__name__)


class BaseClient(ABC):
    """Common functionality shared by LLM clients."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {}  # Subclasses must override

    @staticmethod
    def redact_sensitive_data(
        data: Any,
        redact_keys: tuple = ("api_key", "key", "token", "password", "secret", "authorization"),
    ) -> Any:
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
                k: (
                    "[REDACTED]"
                    if any(key in k.lower() for key in redact_keys)
                    else BaseClient.redact_sensitive_data(v, redact_keys)
                )
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [BaseClient.redact_sensitive_data(item, redact_keys) for item in data]
        if isinstance(data, str):
            # Redact API key patterns (sk-*, anthropic-*, etc.)
            patterns = [
                (r"sk-[a-zA-Z0-9]{20,}", "sk-[REDACTED]"),
                (r"anthropic-[a-zA-Z0-9-]{20,}", "anthropic-[REDACTED]"),
                (r"AIza[a-zA-Z0-9_-]{35}", "AIza[REDACTED]"),  # Google API keys
            ]
            result = data
            for pattern, replacement in patterns:
                result = re.sub(pattern, replacement, result)
            return result
        return data

    @staticmethod
    def get_api_key(agent_config: dict[str, Any]) -> str | None:
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
        from pydantic import SecretStr

        from agent_actions.errors import ConfigurationError

        key_name = agent_config.get(API_KEY_KEY)
        if isinstance(key_name, SecretStr):
            key_name = key_name.get_secret_value()
        if not key_name:
            raise ConfigurationError(
                "API key configuration is missing",
                context={
                    "agent": agent_config.get("agent_type", "unknown"),
                    "field": API_KEY_KEY,
                    "operation": "get_api_key",
                    "hint": "Add api_key to agent_actions.yml, workflow defaults, or action config",
                },
            )
        if key_name.startswith("${") and key_name.endswith("}"):
            env_var_name = key_name[2:-1]
        else:
            env_var_name = key_name
        if env_var_name not in os.environ:
            raise ConfigurationError(
                f"Environment variable '{env_var_name}' is not set",
                context={
                    "agent": agent_config.get("agent_type", "unknown"),
                    "env_var": env_var_name,
                    "config_value": key_name,
                    "operation": "get_api_key",
                    "hint": f"Set the environment variable:\\n  export {env_var_name}=your-api-key",
                },
            )
        api_key = os.getenv(env_var_name)
        if not api_key:
            raise ConfigurationError(
                f"Environment variable '{env_var_name}' is set but empty",
                context={
                    "agent": agent_config.get("agent_type", "unknown"),
                    "env_var": env_var_name,
                    "config_value": key_name,
                    "operation": "get_api_key",
                    "hint": f"Provide a value: export {env_var_name}=your-api-key",
                },
            )
        return api_key

    @staticmethod
    @abstractmethod
    def call_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """
        Call vendor API in JSON mode with schema.

        Args:
            api_key: API key for vendor authentication
            agent_config: Agent configuration dict
            prompt_config: Formatted prompt string
            context_data: Context data for the prompt
            schema: Optional JSON schema for structured output

        Returns:
            List of response dicts
        """

    @staticmethod
    @abstractmethod
    def call_non_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
    ) -> list[dict[str, str]]:
        """
        Call vendor API in non-JSON mode.

        Args:
            api_key: API key for vendor authentication
            agent_config: Agent configuration dict
            prompt_config: Formatted prompt string
            context_data: Context data for the prompt

        Returns:
            List of response dicts
        """

    @classmethod
    def invoke(
        cls,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Dispatch to JSON or non-JSON methods after loading the API key."""
        api_key: str | None = cls.get_api_key(agent_config)
        json_mode: bool = agent_config.get(JSON_MODE_KEY, True)
        if json_mode:
            return cls.call_json(api_key, agent_config, prompt_config, context_data, schema)
        if schema is not None:
            logger.warning(
                "json_mode=false but schema was compiled for action '%s'. "
                "The schema will not be sent to the LLM. "
                "Set json_mode=true to enable schema enforcement.",
                agent_config.get("agent_type", "unknown"),
            )
        return cls.call_non_json(api_key, agent_config, prompt_config, context_data)
