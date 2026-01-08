"""
Ollama client for agent-actions LLM invocation.

Supports:
- Non-JSON mode (plain text responses)
- JSON mode with structured outputs (via format parameter)
- Failure injection for testing online retry (via environment variables)

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.

Failure Injection (for testing online retry):
    OLLAMA_FAILURE_RATE=0.3     # 30% of requests will fail (trigger retry)
    OLLAMA_FAILURE_SEED=42      # Reproducible failures for testing
"""

import json
import logging
import os
import random
from typing import Any, Dict, List, Optional

from ollama import Client, ResponseError
import httpx

from agent_actions.llm_invocation.providers.client_base import BaseClient
from agent_actions.utilities.constants import MODEL_NAME_KEY
from agent_actions.errors import RateLimitError, NetworkError, VendorAPIError

logger = logging.getLogger(__name__)

# Failure injection config (loaded once at module level)
_FAILURE_RATE = float(os.getenv("OLLAMA_FAILURE_RATE", "0"))
_FAILURE_SEED = os.getenv("OLLAMA_FAILURE_SEED", "")
_RNG = random.Random(int(_FAILURE_SEED) if _FAILURE_SEED.isdigit() else None)

if _FAILURE_RATE > 0:
    logger.info("Ollama online failure injection enabled: rate=%.2f", _FAILURE_RATE)


def _maybe_inject_failure() -> None:
    """
    Maybe raise a transient error for testing retry.

    Raises RateLimitError based on OLLAMA_FAILURE_RATE.
    """
    if _FAILURE_RATE > 0 and _RNG.random() < _FAILURE_RATE:
        logger.info("[INJECTED FAILURE] Simulating rate limit for retry testing")
        raise RateLimitError(
            "Simulated rate limit (injected for testing)",
            context={"vendor": "ollama", "injected": True, "retry_after": 1},
        )


# Reprompt failure injection config
_REPROMPT_TEST_MODE = os.getenv("REPROMPT_TEST_MODE", "").lower()
_REPROMPT_FAILURE_RATE = float(os.getenv("REPROMPT_FAILURE_RATE", "0.5"))
_REPROMPT_SUCCESS_AFTER = int(os.getenv("REPROMPT_SUCCESS_AFTER", "2"))
_reprompt_failure_count = 0

# Skip JSON repair in client for testing (allows malformed JSON to reach interceptor)
_SKIP_JSON_REPAIR_IN_CLIENT = os.getenv("SKIP_JSON_REPAIR_IN_CLIENT", "").lower() == "true"

if _SKIP_JSON_REPAIR_IN_CLIENT:
    logger.info("JSON repair disabled in client for testing")

if _REPROMPT_TEST_MODE:
    logger.info(
        "Ollama reprompt failure injection enabled: mode=%s, rate=%.2f, success_after=%d",
        _REPROMPT_TEST_MODE,
        _REPROMPT_FAILURE_RATE,
        _REPROMPT_SUCCESS_AFTER,
    )

# Malformed JSON samples for testing
_MALFORMED_SAMPLES = [
    '```json\n{"name": "test", "value": 123}\n```',  # Markdown wrapped
    '{"name": "test", "items": [1, 2, 3,]}',  # Trailing comma
    "{'name': 'test', 'value': 123}",  # Single quotes
    '{"name": "test", "items": [1, 2, 3',  # Unclosed bracket
]


def _maybe_inject_reprompt_failure(valid_response: Any) -> Any:
    """
    Maybe inject malformed response for testing reprompt.

    Returns either the valid response or an injected malformed response.
    """
    global _reprompt_failure_count

    if not _REPROMPT_TEST_MODE:
        return valid_response

    # Allow success after N failures
    if _reprompt_failure_count >= _REPROMPT_SUCCESS_AFTER:
        _reprompt_failure_count = 0
        logger.info("[REPROMPT TEST] Allowing success after %d failures", _REPROMPT_SUCCESS_AFTER)
        return valid_response

    if _RNG.random() < _REPROMPT_FAILURE_RATE:
        _reprompt_failure_count += 1

        if _REPROMPT_TEST_MODE == "malformed_json":
            sample = _RNG.choice(_MALFORMED_SAMPLES)
            logger.info("[INJECTED REPROMPT FAILURE] Returning malformed JSON: %s...", sample[:40])
            return sample

        if _REPROMPT_TEST_MODE == "missing_fields":
            logger.info("[INJECTED REPROMPT FAILURE] Returning response with missing fields")
            return {"_partial": True, "injected_error": "missing_fields"}

    return valid_response


def _wrap_ollama_error(e: Exception, model_name: str) -> Exception:
    """Wrap Ollama errors into unified agent-actions error types.

    Args:
        e: The Ollama exception
        model_name: Model name for context

    Returns:
        Wrapped exception (RateLimitError, NetworkError, or VendorAPIError)
    """
    context = {"vendor": "ollama", "model": model_name}

    # Connection errors (Ollama uses httpx)
    if isinstance(e, httpx.ConnectError):
        return NetworkError(f"Ollama connection error: {e}", context=context, cause=e)

    if isinstance(e, httpx.TimeoutException):
        return NetworkError(f"Ollama timeout: {e}", context=context, cause=e)

    if isinstance(e, httpx.HTTPStatusError):
        status_code = e.response.status_code
        if status_code == 429:
            return RateLimitError(f"Ollama rate limit: {e}", context=context, cause=e)
        if status_code in (502, 503, 504):
            return NetworkError(f"Ollama server error: {e}", context=context, cause=e)
        return VendorAPIError(f"Ollama HTTP error: {e}", context=context, cause=e)

    # Ollama ResponseError
    if isinstance(e, ResponseError):
        return VendorAPIError(f"Ollama error: {e}", context=context, cause=e)

    # Unknown error, re-raise as-is
    return e


class OllamaClient(BaseClient):
    """
    Ollama local LLM client for JSON and non-JSON invocations.

    Supports structured outputs via Ollama's `format` parameter.
    Supports failure injection via environment variables for testing retry.
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
        # Check for failure injection (for testing retry)
        _maybe_inject_failure()

        model = agent_config[MODEL_NAME_KEY]
        ctx_str = (
            json.dumps(context_data, ensure_ascii=False)
            if not isinstance(context_data, str)
            else context_data
        )
        messages = OllamaClient._prep_messages(prompt_config, ctx_str)

        # Extract schema for Ollama's format parameter
        ollama_schema = OllamaClient._extract_ollama_schema(schema)

        logger.debug("Calling Ollama with JSON mode, schema=%s", bool(ollama_schema))

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
            raise _wrap_ollama_error(e, model) from e

        # Parse JSON response
        content = response.message.content

        # Inject reprompt failure if testing (returns malformed content)
        content = _maybe_inject_reprompt_failure(content)

        # If injection returned a string (malformed JSON), try to repair then parse
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    return [parsed]
                return [{"response": parsed}]
            except json.JSONDecodeError as e:
                # Try JSON repair before giving up
                from agent_actions.reprompting.json_repair import JSONRepairStrategy

                repair = JSONRepairStrategy()
                repair_result = repair.attempt_repair(content)

                if repair_result.success and not _SKIP_JSON_REPAIR_IN_CLIENT:
                    logger.info(
                        "JSON repaired using %s: %s",
                        repair_result.repair_method,
                        str(repair_result.data)[:100],
                    )
                    if isinstance(repair_result.data, dict):
                        return [repair_result.data]
                    return [{"response": repair_result.data}]

                # Repair failed or skipped - return raw content for reprompt handling
                if _SKIP_JSON_REPAIR_IN_CLIENT:
                    logger.info("JSON repair skipped for testing - returning raw content")
                else:
                    logger.warning("Failed to parse/repair Ollama JSON response: %s", e)
                return [{"raw_response": content, "_parse_error": str(e)}]

        # If injection returned a dict (missing fields), return directly
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
        # Check for failure injection (for testing retry)
        _maybe_inject_failure()

        model = agent_config[MODEL_NAME_KEY]
        ctx_str = (
            json.dumps(context_data, ensure_ascii=False)
            if not isinstance(context_data, str)
            else context_data
        )
        messages = OllamaClient._prep_messages(prompt_config, ctx_str)

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
            raise _wrap_ollama_error(e, model) from e

        output_field = agent_config.get("output_field", "raw_response")
        response_content = {output_field: response.message.content}
        return [response_content]
