"""
Ollama client for agent-actions LLM invocation.
"""

import json
import os
from ollama import Client
from agent_actions.llm_invocation.providers.client_base import BaseClient
from agent_actions.utilities.constants import MODEL_NAME_KEY


class OllamaClient(BaseClient):
    """Ollama local LLM client for JSON and non-JSON invocations."""

    @staticmethod
    def _prep_messages(prompt_config: str, context_data: str):
        """Prepare messages with system and user roles."""
        return [
            {"role": "system", "content": prompt_config},
            {"role": "user", "content": context_data},
        ]

    @staticmethod
    def _get_client(agent_config) -> Client:
        """Return an Ollama Client pointed at the correct host."""
        host = agent_config.get("base_url") or os.getenv("OLLAMA_HOST")
        return Client(host=host) if host else Client()

    @classmethod
    def invoke(cls, agent_config, prompt_config, context_data, schema=None):
        """
        Override invoke to enforce Ollama does NOT support JSON mode.

        Raises:
            ConfigurationError: If json_mode is enabled for Ollama
        """
        from agent_actions.utilities.constants import JSON_MODE_KEY
        from agent_actions.errors import ConfigurationError  # New modular pattern!

        json_mode = agent_config.get(JSON_MODE_KEY, True)
        if json_mode:
            raise ConfigurationError(
                "Ollama does not support json_mode=true. Structured output is unreliable with Ollama models.",
                context={
                    "vendor": "ollama",
                    "model": agent_config.get("model_name", "unknown"),
                    "json_mode": json_mode,
                    "operation": "invoke",
                    "hint": "Set json_mode: false in your agent configuration or workflow defaults",
                },
            )
        api_key = None
        try:
            api_key = cls.get_api_key(agent_config)
        except (KeyError, AttributeError, TypeError):
            pass
        return cls.call_non_json(api_key, agent_config, prompt_config, context_data)

    @staticmethod
    def call_json(_api_key, _agent_config, _prompt_config, _context_data, _schema):
        """
        NOTE: This method should not be called for Ollama.
        The invoke() method enforces json_mode=false.

        Kept for interface compatibility.
        """
        raise NotImplementedError(
            "Ollama does not support JSON mode. This method should never be called due to invoke() validation."
        )

    @staticmethod
    def call_non_json(_api_key, agent_config, prompt_config, context_data, _schema=None):
        """
        Plain-text chat (no schema enforcement).
        This is the ONLY supported mode for Ollama.
        """
        model = agent_config[MODEL_NAME_KEY]
        ctx_str = (
            json.dumps(context_data, ensure_ascii=False)
            if not isinstance(context_data, str)
            else context_data
        )
        messages = OllamaClient._prep_messages(prompt_config, ctx_str)
        response = OllamaClient._get_client(agent_config).chat(
            model=model, messages=messages, stream=False
        )
        output_field = agent_config.get("output_field", "raw_response")
        response_content = {output_field: response.message.content}
        return [response_content]
