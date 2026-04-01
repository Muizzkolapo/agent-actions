"""
Ollama client for agent-actions LLM invocation.

Supports:
- Non-JSON mode (plain text responses)
- JSON mode with structured outputs (via format parameter)

SDK errors are wrapped into unified agent-actions error types.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, ClassVar

import httpx
from ollama import Client, ResponseError

from agent_actions.errors import ConfigurationError, VendorAPIError
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.generation_params import extract_generation_params
from agent_actions.llm.providers.ollama.failure_injection import (
    maybe_inject_online_failure,
)
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    LLMRequestEvent,
)
from agent_actions.logging.events.llm_events import LLMJSONParseErrorEvent
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.prompt.message_builder import MessageBuilder
from agent_actions.utils.constants import MODEL_NAME_KEY

logger = logging.getLogger(__name__)


_ERROR_MAPPING = VendorErrorMapping(
    vendor_name="ollama",
    extra_network_types=(httpx.ConnectError, httpx.TimeoutException),
    status_code_error_types=(httpx.HTTPStatusError,),
    base_api_error_type=ResponseError,
    supports_retry_after=False,
)


def _wrap_ollama_error(e: Exception, model_name: str, request_id: str = "") -> Exception:
    """Wrap Ollama errors into unified agent-actions error types."""
    return wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id)


class OllamaClient(BaseClient):
    """
    Ollama local LLM client for JSON and non-JSON invocations.

    Supports structured outputs via Ollama's `format` parameter.
    """

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": False,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["base_url", "temperature", "max_tokens"],
    }

    @staticmethod
    def _get_client(agent_config: dict[str, Any]) -> Client:
        """Return an Ollama Client pointed at the correct host."""
        host = agent_config.get("base_url") or os.getenv("OLLAMA_HOST")
        return Client(host=host) if host else Client()

    @staticmethod
    def _extract_ollama_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
        """
        Extract the inner JSON schema for Ollama's format parameter.

        OpenAI format: {"name": "...", "strict": true, "schema": {...}}
        Ollama expects: {"type": "object", "properties": {...}, "required": [...]}
        """
        if not schema:
            return None

        if not isinstance(schema, dict):
            raise ConfigurationError(f"Schema must be a dict, got {type(schema).__name__}")

        # If schema has nested "schema" key (OpenAI format), extract it
        if "schema" in schema and isinstance(schema["schema"], dict):
            return schema["schema"]

        # If it's already a raw JSON schema, return as-is
        if "type" in schema or "properties" in schema:
            return schema

        raise ConfigurationError(f"Unrecognised schema format (keys: {list(schema.keys())})")

    @staticmethod
    def call_json(  # type: ignore[override]
        _api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: Any,
        schema: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Call Ollama API in JSON mode with structured output.

        Uses Ollama's `format` parameter to enforce JSON schema.

        Args:
            _api_key: Not used for Ollama (local model)
            agent_config: Agent configuration with model_name
            prompt_config: System prompt
            context_data: User context (string or dict)
            schema: JSON schema for structured output

        Returns:
            List with single response dict containing parsed JSON fields
        """
        model = agent_config[MODEL_NAME_KEY]
        envelope = MessageBuilder.build(
            "ollama", prompt_config, context_data, schema=schema, json_mode=True
        )
        messages = envelope.to_dicts()

        # Extract schema for Ollama's format parameter
        logger.debug("Schema received by Ollama client: type=%s, value=%s", type(schema), schema)
        ollama_schema = OllamaClient._extract_ollama_schema(schema)
        logger.debug(
            "Schema after extraction: type=%s, value=%s", type(ollama_schema), ollama_schema
        )

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        # Fire LLM request event
        fire_event(
            LLMRequestEvent(
                provider="ollama",
                model=model,
                request_id=request_id,
            )
        )

        logger.debug("Calling Ollama with JSON mode, schema=%s", bool(ollama_schema))

        options = extract_generation_params(
            agent_config,
            key_map={"max_tokens": "num_predict"},
            stop_as_list=True,
        )

        start_time = datetime.now()
        try:
            chat_kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": False,
                "format": ollama_schema if ollama_schema else "json",
            }
            if options:
                chat_kwargs["options"] = options
            response = OllamaClient._get_client(agent_config).chat(**chat_kwargs)
        except (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.HTTPStatusError,
            ResponseError,
        ) as e:
            raise _wrap_ollama_error(e, model, request_id) from e

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        ResponseBuilder.record_usage_and_event(response, "ollama", model, latency_ms, request_id)

        # Failure injection AFTER successful call - simulates "got nothing back"
        maybe_inject_online_failure(model)

        # Parse JSON response
        content = response.message.content

        if isinstance(content, str):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    return [parsed]
                return [{"response": parsed}]
            except json.JSONDecodeError as e:
                logger.debug("JSON parse failed: %s, request_id=%s", e, request_id)
                fire_event(
                    LLMJSONParseErrorEvent(
                        provider="ollama",
                        model=model,
                        error=str(e),
                    )
                )
                raise VendorAPIError(
                    f"Ollama returned invalid JSON: {e}",
                    context={"vendor": "ollama", "request_id": request_id},
                    cause=e,
                ) from e

        if isinstance(content, dict):
            return [content]

        return [{"response": content}]

    @staticmethod
    def call_non_json(  # type: ignore[override]
        _api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: Any,
        _schema: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        """
        Plain-text chat (no schema enforcement).

        Args:
            _api_key: Not used for Ollama (local model)
            agent_config: Agent configuration with model_name and output_field
            prompt_config: System prompt
            context_data: User context (string or dict)
            _schema: Ignored for non-JSON mode

        Returns:
            List with single response dict containing output_field
        """
        model = agent_config[MODEL_NAME_KEY]
        envelope = MessageBuilder.build("ollama", prompt_config, context_data, json_mode=False)
        messages = envelope.to_dicts()

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        # Fire LLM request event
        fire_event(
            LLMRequestEvent(
                provider="ollama",
                model=model,
                request_id=request_id,
            )
        )

        start_time = datetime.now()
        try:
            non_json_options = extract_generation_params(
                agent_config,
                key_map={"max_tokens": "num_predict"},
                stop_as_list=True,
            )
            non_json_kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": False,
            }
            if non_json_options:
                non_json_kwargs["options"] = non_json_options
            response = OllamaClient._get_client(agent_config).chat(**non_json_kwargs)
        except (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.HTTPStatusError,
            ResponseError,
        ) as e:
            raise _wrap_ollama_error(e, model, request_id) from e

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        ResponseBuilder.record_usage_and_event(response, "ollama", model, latency_ms, request_id)

        # Failure injection AFTER successful call - simulates "got nothing back"
        maybe_inject_online_failure(model)

        return ResponseBuilder.wrap_non_json(response.message.content, agent_config)
