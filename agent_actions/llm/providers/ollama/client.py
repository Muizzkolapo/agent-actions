"""
Ollama clients for agent-actions LLM invocation.

Two clients share a single implementation kernel parameterized by ``cloud``:
- **OllamaLocalClient** — local daemon, no auth, API-enforced structured output
- **OllamaCloudClient** — ollama.com, Bearer auth, prompt-injected schema

When Ollama Cloud adds structured output support (ollama/ollama#12362),
remove the ``if not cloud`` guard on the ``format`` kwarg and change cloud's
ProviderMessageConfig from SchemaInjection.PROMPT to SchemaInjection.NONE.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, ClassVar

import httpx
from ollama import Client, ResponseError

from agent_actions.config.defaults import OllamaCloudDefaults
from agent_actions.errors import ConfigurationError, VendorAPIError
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.generation_params import extract_generation_params
from agent_actions.llm.providers.ollama.failure_injection import (
    maybe_inject_online_failure,
)
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import LLMRequestEvent
from agent_actions.logging.events.llm_events import LLMJSONParseErrorEvent
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.prompt.message_builder import MessageBuilder
from agent_actions.utils.constants import JSON_MODE_KEY, MODEL_NAME_KEY

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers (the "kernel")
# ---------------------------------------------------------------------------


def _error_mapping(vendor_slug: str) -> VendorErrorMapping:
    return VendorErrorMapping(
        vendor_name=vendor_slug,
        extra_network_types=(httpx.ConnectError, httpx.TimeoutException),
        status_code_error_types=(httpx.HTTPStatusError,),
        base_api_error_type=ResponseError,
        supports_retry_after=False,
    )


def _build_ollama_client(
    agent_config: dict[str, Any],
    api_key: str | None = None,
    *,
    cloud: bool = False,
) -> Client:
    """Build an ``ollama.Client`` with correct host and optional Bearer auth."""
    if cloud:
        host = agent_config.get("base_url") or os.getenv(
            "OLLAMA_CLOUD_HOST", OllamaCloudDefaults.BASE_URL
        )
        if not api_key:
            raise ConfigurationError(
                "ollama_cloud requires an API key",
                context={
                    "vendor": "ollama_cloud",
                    "hint": (
                        "Set api_key in your action config or export OLLAMA_API_KEY. "
                        "Create a key at https://ollama.com/settings/keys"
                    ),
                },
            )
        return Client(host=host, headers={"Authorization": f"Bearer {api_key}"})

    host = agent_config.get("base_url") or os.getenv("OLLAMA_HOST")
    return Client(host=host) if host else Client()


def _extract_ollama_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract inner JSON schema for Ollama's ``format`` parameter.

    OpenAI wraps as ``{"name": "...", "schema": {...}}``; Ollama expects the
    raw ``{"type": "object", "properties": {...}}`` directly.
    """
    if not schema:
        return None
    if not isinstance(schema, dict):
        raise ConfigurationError(f"Schema must be a dict, got {type(schema).__name__}")
    if "schema" in schema and isinstance(schema["schema"], dict):
        return schema["schema"]
    if "type" in schema or "properties" in schema:
        return schema
    raise ConfigurationError(f"Unrecognised schema format (keys: {list(schema.keys())})")


def _call_ollama_json(
    api_key: str | None,
    agent_config: dict[str, Any],
    prompt_config: str,
    context_data: Any,
    schema: dict[str, Any] | None,
    *,
    vendor_slug: str,
    cloud: bool,
) -> list[dict[str, Any]]:
    """JSON-mode invocation shared by local and cloud clients."""
    model = agent_config[MODEL_NAME_KEY]
    envelope = MessageBuilder.build(
        vendor_slug, prompt_config, context_data, schema=schema, json_mode=True
    )
    messages = envelope.to_dicts()

    ollama_schema = _extract_ollama_schema(schema)
    request_id = str(uuid.uuid4())

    fire_event(LLMRequestEvent(provider=vendor_slug, model=model, request_id=request_id))
    logger.debug("Calling Ollama with JSON mode, schema=%s, cloud=%s", bool(ollama_schema), cloud)

    options = extract_generation_params(
        agent_config, key_map={"max_tokens": "num_predict"}, stop_as_list=True
    )

    start_time = datetime.now()
    try:
        chat_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        # Local: API-enforced structured output via format param.
        # Cloud: schema already injected into prompt by MessageBuilder
        # (SchemaInjection.PROMPT). Remove this guard when Ollama Cloud
        # supports structured outputs (ollama/ollama#12362).
        if not cloud:
            chat_kwargs["format"] = ollama_schema if ollama_schema else "json"
        if options:
            chat_kwargs["options"] = options
        client = _build_ollama_client(agent_config, api_key, cloud=cloud)
        response = client.chat(**chat_kwargs)
    except (
        httpx.ConnectError,
        httpx.TimeoutException,
        httpx.HTTPStatusError,
        ResponseError,
    ) as e:
        raise wrap_vendor_error(e, model, _error_mapping(vendor_slug), request_id) from e

    latency_ms = (datetime.now() - start_time).total_seconds() * 1000
    ResponseBuilder.record_usage_and_event(response, vendor_slug, model, latency_ms, request_id)
    maybe_inject_online_failure(model, vendor_slug=vendor_slug)

    content = response.message.content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            return [parsed] if isinstance(parsed, dict) else [{"response": parsed}]
        except json.JSONDecodeError as e:
            logger.debug("JSON parse failed: %s, request_id=%s", e, request_id)
            fire_event(LLMJSONParseErrorEvent(provider=vendor_slug, model=model, error=str(e)))
            raise VendorAPIError(
                f"Ollama returned invalid JSON: {e}",
                context={"vendor": vendor_slug, "request_id": request_id},
                cause=e,
            ) from e
    if isinstance(content, dict):
        return [content]
    return [{"response": content}]


def _call_ollama_non_json(
    api_key: str | None,
    agent_config: dict[str, Any],
    prompt_config: str,
    context_data: Any,
    *,
    vendor_slug: str,
    cloud: bool,
) -> list[dict[str, str]]:
    """Non-JSON invocation shared by local and cloud clients."""
    model = agent_config[MODEL_NAME_KEY]
    envelope = MessageBuilder.build(vendor_slug, prompt_config, context_data, json_mode=False)
    messages = envelope.to_dicts()

    request_id = str(uuid.uuid4())
    fire_event(LLMRequestEvent(provider=vendor_slug, model=model, request_id=request_id))

    start_time = datetime.now()
    try:
        non_json_options = extract_generation_params(
            agent_config, key_map={"max_tokens": "num_predict"}, stop_as_list=True
        )
        chat_kwargs: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if non_json_options:
            chat_kwargs["options"] = non_json_options
        client = _build_ollama_client(agent_config, api_key, cloud=cloud)
        response = client.chat(**chat_kwargs)
    except (
        httpx.ConnectError,
        httpx.TimeoutException,
        httpx.HTTPStatusError,
        ResponseError,
    ) as e:
        raise wrap_vendor_error(e, model, _error_mapping(vendor_slug), request_id) from e

    latency_ms = (datetime.now() - start_time).total_seconds() * 1000
    ResponseBuilder.record_usage_and_event(response, vendor_slug, model, latency_ms, request_id)
    maybe_inject_online_failure(model, vendor_slug=vendor_slug)

    return ResponseBuilder.wrap_non_json(response.message.content, agent_config)


# ---------------------------------------------------------------------------
# Public client classes
# ---------------------------------------------------------------------------


class OllamaLocalClient(BaseClient):
    """Ollama local daemon client — no auth, API-enforced structured output."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["base_url", "temperature", "max_tokens"],
    }

    @classmethod
    def invoke(
        cls,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Dispatch without loading an API key — local daemon needs none."""
        json_mode: bool = agent_config.get(JSON_MODE_KEY, True)
        if json_mode:
            return _call_ollama_json(
                None,
                agent_config,
                prompt_config,
                context_data,
                schema,
                vendor_slug="ollama_local",
                cloud=False,
            )
        if schema is not None:
            logger.warning(
                "json_mode=false but schema was compiled for action '%s'. "
                "The schema will not be sent to the LLM.",
                agent_config["agent_type"],
            )
        return _call_ollama_non_json(
            None,
            agent_config,
            prompt_config,
            context_data,
            vendor_slug="ollama_local",
            cloud=False,
        )

    @staticmethod
    def call_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: Any,
        schema: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return _call_ollama_json(
            api_key,
            agent_config,
            prompt_config,
            context_data,
            schema,
            vendor_slug="ollama_local",
            cloud=False,
        )

    @staticmethod
    def call_non_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: Any,
        _schema: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        return _call_ollama_non_json(
            api_key,
            agent_config,
            prompt_config,
            context_data,
            vendor_slug="ollama_local",
            cloud=False,
        )


class OllamaCloudClient(BaseClient):
    """Ollama Cloud client — Bearer auth, prompt-injected schema."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["base_url", "temperature", "max_tokens", "api_key"],
    }

    @staticmethod
    def call_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: Any,
        schema: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return _call_ollama_json(
            api_key,
            agent_config,
            prompt_config,
            context_data,
            schema,
            vendor_slug="ollama_cloud",
            cloud=True,
        )

    @staticmethod
    def call_non_json(
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: Any,
        _schema: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        return _call_ollama_non_json(
            api_key,
            agent_config,
            prompt_config,
            context_data,
            vendor_slug="ollama_cloud",
            cloud=True,
        )
