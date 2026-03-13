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
from typing import Any

import httpx
from ollama import Client, ResponseError

from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.generation_params import extract_generation_params
from agent_actions.llm.providers.ollama.failure_injection import (
    maybe_inject_online_failure,
)
from agent_actions.llm.providers.usage_tracker import set_last_usage
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    LLMRequestEvent,
    LLMResponseEvent,
)
from agent_actions.logging.events.llm_events import LLMJSONParseErrorEvent
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

    @staticmethod
    def _prep_messages(prompt_config: str, context_data: str) -> list[dict[str, str]]:
        """Prepare messages with system and user roles."""
        return [
            {"role": "system", "content": prompt_config},
            {"role": "user", "content": context_data},
        ]

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

        # If schema is a tuple (shouldn't happen but handle it)
        if isinstance(schema, tuple):
            logger.warning("Schema is a tuple, extracting first element: %s", schema)
            schema = schema[0] if schema else None
            if not schema:
                return None

        # Ensure schema is a dict
        if not isinstance(schema, dict):
            logger.warning("Schema is not a dict (type=%s), returning None", type(schema))
            return None

        # If schema has nested "schema" key (OpenAI format), extract it
        if "schema" in schema and isinstance(schema["schema"], dict):
            return schema["schema"]

        # If it's already a raw JSON schema, return as-is
        if "type" in schema or "properties" in schema:
            return schema

        return schema

    @staticmethod
    def call_json(
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
        ctx_str = (
            json.dumps(context_data, ensure_ascii=False)
            if not isinstance(context_data, str)
            else context_data
        )
        messages = OllamaClient._prep_messages(prompt_config, ctx_str)

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

        # Extract token counts from Ollama response
        prompt_tokens = getattr(response, "prompt_eval_count", 0) or 0
        completion_tokens = getattr(response, "eval_count", 0) or 0
        total_tokens = prompt_tokens + completion_tokens

        if total_tokens > 0:
            set_last_usage(
                {
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
            )

        # Fire LLM response event
        fire_event(
            LLMResponseEvent(
                provider="ollama",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                request_id=request_id,
            )
        )

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
                return [{"raw_response": content, "_parse_error": str(e)}]

        if isinstance(content, dict):
            return [content]

        return [{"response": content}]

    @staticmethod
    def call_non_json(
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
        ctx_str = (
            json.dumps(context_data, ensure_ascii=False)
            if not isinstance(context_data, str)
            else context_data
        )
        messages = OllamaClient._prep_messages(prompt_config, ctx_str)

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

        # Extract token counts from Ollama response
        prompt_tokens = getattr(response, "prompt_eval_count", 0) or 0
        completion_tokens = getattr(response, "eval_count", 0) or 0
        total_tokens = prompt_tokens + completion_tokens

        if total_tokens > 0:
            set_last_usage(
                {
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
            )

        # Fire LLM response event
        fire_event(
            LLMResponseEvent(
                provider="ollama",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                request_id=request_id,
            )
        )

        # Failure injection AFTER successful call - simulates "got nothing back"
        maybe_inject_online_failure(model)

        output_field = agent_config.get("output_field", "raw_response")
        response_content = {output_field: response.message.content}
        return [response_content]
