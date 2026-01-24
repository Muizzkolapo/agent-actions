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
from typing import Any, Dict, List, Optional

from ollama import Client, ResponseError
import httpx

from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.utils.constants import MODEL_NAME_KEY
from agent_actions.errors import RateLimitError, NetworkError, VendorAPIError
from agent_actions.llm.providers.ollama.failure_injection import (
    maybe_inject_online_failure,
)
from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    LLMRequestEvent,
    LLMResponseEvent,
    LLMErrorEvent,
    RateLimitEvent,
)
from agent_actions.logging.events.types import LLMJSONParseErrorEvent

logger = logging.getLogger(__name__)


def _wrap_ollama_error(e: Exception, model_name: str, request_id: str = "") -> Exception:
    """Wrap Ollama errors into unified agent-actions error types.

    Also fires appropriate LLM events.

    Args:
        e: The Ollama exception
        model_name: Model name for context
        request_id: Request ID for correlation

    Returns:
        Wrapped exception (RateLimitError, NetworkError, or VendorAPIError)
    """
    context = {"vendor": "ollama", "model": model_name}

    # Connection errors (Ollama uses httpx)
    if isinstance(e, httpx.ConnectError):
        fire_event(
            LLMErrorEvent(
                provider="ollama",
                model=model_name,
                error_type="ConnectError",
                error_message=str(e),
                request_id=request_id,
            )
        )
        return NetworkError(f"Ollama connection error: {e}", context=context, cause=e)

    if isinstance(e, httpx.TimeoutException):
        fire_event(
            LLMErrorEvent(
                provider="ollama",
                model=model_name,
                error_type="TimeoutException",
                error_message=str(e),
                request_id=request_id,
            )
        )
        return NetworkError(f"Ollama timeout: {e}", context=context, cause=e)

    if isinstance(e, httpx.HTTPStatusError):
        status_code = e.response.status_code
        if status_code == 429:
            fire_event(
                RateLimitEvent(
                    provider="ollama",
                    retry_after=0.0,
                    request_id=request_id,
                )
            )
            return RateLimitError(f"Ollama rate limit: {e}", context=context, cause=e)
        if status_code in (502, 503, 504):
            fire_event(
                LLMErrorEvent(
                    provider="ollama",
                    model=model_name,
                    error_type="ServerError",
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            return NetworkError(f"Ollama server error: {e}", context=context, cause=e)
        fire_event(
            LLMErrorEvent(
                provider="ollama",
                model=model_name,
                error_type="HTTPStatusError",
                error_message=str(e),
                request_id=request_id,
            )
        )
        return VendorAPIError(f"Ollama HTTP error: {e}", context=context, cause=e)

    # Ollama ResponseError
    if isinstance(e, ResponseError):
        fire_event(
            LLMErrorEvent(
                provider="ollama",
                model=model_name,
                error_type="ResponseError",
                error_message=str(e),
                request_id=request_id,
            )
        )
        return VendorAPIError(f"Ollama error: {e}", context=context, cause=e)

    # Unknown error, re-raise as-is
    return e


class OllamaClient(BaseClient):
    """
    Ollama local LLM client for JSON and non-JSON invocations.

    Supports structured outputs via Ollama's `format` parameter.
    """

    @staticmethod
    def _prep_messages(prompt_config: str, context_data: str) -> List[Dict[str, str]]:
        """Prepare messages with system and user roles."""
        return [
            {"role": "system", "content": prompt_config},
            {"role": "user", "content": context_data},
        ]

    @staticmethod
    def _get_client(agent_config: Dict[str, Any]) -> Client:
        """Return an Ollama Client pointed at the correct host."""
        host = agent_config.get("base_url") or os.getenv("OLLAMA_HOST")
        return Client(host=host) if host else Client()

    @staticmethod
    def _extract_ollama_schema(schema: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
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
        _api_key: Optional[str],
        agent_config: Dict[str, Any],
        prompt_config: str,
        context_data: Any,
        schema: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
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

        start_time = datetime.now()
        try:
            response = OllamaClient._get_client(agent_config).chat(
                model=model,
                messages=messages,
                stream=False,
                format=ollama_schema if ollama_schema else "json",
            )
        except (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.HTTPStatusError,
            ResponseError,
        ) as e:
            raise _wrap_ollama_error(e, model, request_id) from e

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        # Ollama doesn't provide token counts in the same way, use 0 as default
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

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
                # Return raw content with error info
                logger.debug("JSON parse failed: %s, request_id=%s", e, request_id)
                fire_event(LLMJSONParseErrorEvent(
                    provider="ollama",
                    model=model,
                    error=str(e),
                ))
                return [{"raw_response": content, "_parse_error": str(e)}]

        if isinstance(content, dict):
            return [content]

        return [{"response": content}]

    @staticmethod
    def call_non_json(
        _api_key: Optional[str],
        agent_config: Dict[str, Any],
        prompt_config: str,
        context_data: Any,
        _schema: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
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
            response = OllamaClient._get_client(agent_config).chat(
                model=model, messages=messages, stream=False
            )
        except (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.HTTPStatusError,
            ResponseError,
        ) as e:
            raise _wrap_ollama_error(e, model, request_id) from e

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        # Ollama doesn't provide token counts in the same way, use 0 as default
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

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
