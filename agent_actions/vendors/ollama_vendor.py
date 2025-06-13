"""
agent_actions.vendors.ollama_vendor
-----------------------------------
A mirror of OpenAIHandler that supports:

* Structured output via the `format=` parameter.
* Optional host override with either:
    • agent_config["base_url"]  (highest priority)
    • the environment variable OLLAMA_HOST
    • default http://localhost:11434
"""

import json
import os

from ollama import Client                         # <— changed
from agent_actions.vendors.base_vendor import BaseVendorHandler


class OllamaHandler(BaseVendorHandler):
    # ---------- helpers -------------------------------------------------- #
    @staticmethod
    def _prep_messages(prompt_config: str, context_data: str):
        """Prepare messages with system and user roles."""
        return [
            {"role": "system", "content": prompt_config},
            {"role": "user", "content": context_data}
        ]

    @staticmethod
    def _get_client(agent_config) -> Client:
        """Return an Ollama Client pointed at the correct host."""
        host = agent_config.get("base_url") or os.getenv("OLLAMA_HOST")
        return Client(host=host) if host else Client()        # default = localhost:11434

    # ---------- public entry-points -------------------------------------- #
    @staticmethod
    def call_json(agent_config, prompt_config, context_data, schema):
        """
        Enforce the supplied JSON schema and return a list of dicts.
        """
        model = agent_config["model_name"]
        if hasattr(schema, "model_json_schema"):
            schema = schema.model_json_schema()               # allow Pydantic models

        #ctx_str  = StringProcessor.process_as_string(context_data)
        # OllamaHandler.call_json / call_non_json
        ctx_str = (json.dumps(context_data, ensure_ascii=False) if not isinstance(context_data, str) else context_data)

        messages = OllamaHandler._prep_messages(prompt_config, ctx_str)

        response = OllamaHandler._get_client(agent_config).chat(
            model=model,
            messages=messages,
            format=schema,                                   # structured output
            stream=False
        )
        data = json.loads(response.message.content)
        return data if isinstance(data, list) else [data]


    @staticmethod
    def call_non_json(agent_config, prompt_config, context_data, schema=None):
        """
        Plain-text chat (no schema enforcement).
        """
        model = agent_config["model_name"]
        ctx_str = (
            json.dumps(context_data, ensure_ascii=False)
            if not isinstance(context_data, str)
            else context_data
        )
        messages = OllamaHandler._prep_messages(prompt_config, ctx_str)

        response = OllamaHandler._get_client(agent_config).chat(
            model=model,
            messages=messages,
            stream=False
        )
        response_content = {"raw_response": response.message.content}
        return [response_content]


