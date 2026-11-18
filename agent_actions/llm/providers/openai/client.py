"""
OpenAI client for agent-actions.

Provides implementation of call_json() and call_non_json() methods
for OpenAI API integration, supporting GPT models.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import logging
import time
import uuid
from dataclasses import replace
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

import openai
from openai import OpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import (
    NoAnswer,
    VendorErrorMapping,
    chat_no_answer,
    cut_off_parse_error,
    is_truncated,
    unparsed_json_record,
    wrap_vendor_error,
)
from agent_actions.llm.providers.generation_params import (
    ALWAYS_RESERVED,
    VendorParamSpec,
    connect_limited_timeout_kwargs,
    extract_generation_params,
    sdk_keyword_params,
)
from agent_actions.llm.providers.sdk_models import build_sdk_models
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    LLMErrorEvent,
    LLMRequestEvent,
)
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.prompt.message_builder import MessageBuilder
from agent_actions.utils.constants import MODEL_NAME_KEY

build_sdk_models(ChatCompletion)

_ERROR_MAPPING = VendorErrorMapping(
    vendor_name="openai",
    rate_limit_types=(openai.RateLimitError,),
    network_error_types=(
        openai.APIConnectionError,
        openai.APITimeoutError,
        openai.InternalServerError,
    ),
    base_api_error_type=openai.APIError,
    supports_retry_after=True,
)


class OpenAIClient(BaseClient):
    """OpenAI API client for JSON and non-JSON LLM invocations."""

    # The vendor its events and errors name; a runtime profile client sets its own.
    VENDOR: ClassVar[str] = "openai"

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "base_url", "temperature", "max_tokens"],
    }
    VENDOR_PARAMS: ClassVar[VendorParamSpec] = VendorParamSpec(
        accepted=sdk_keyword_params(openai.resources.chat.completions.Completions.create),
        reserved=ALWAYS_RESERVED | {"stream_options"},
        merged=frozenset({"extra_headers", "extra_body", "extra_query"}),
    )

    @classmethod
    def _error_mapping(cls) -> VendorErrorMapping:
        return replace(_ERROR_MAPPING, vendor_name=cls.VENDOR)

    @classmethod
    def _client_options(cls, agent_config: dict[str, Any]) -> dict[str, Any]:
        """Constructor kwargs for the SDK client; a declared endpoint adds headers and a timeout."""
        return {"base_url": agent_config.get("base_url")}

    @classmethod
    def _request_timeout_kwargs(cls, agent_config: dict[str, Any]) -> dict[str, Any]:
        return connect_limited_timeout_kwargs(agent_config, openai)

    @classmethod
    def _request_headers(cls) -> dict[str, Any]:
        """Headers each request sends beside the client's own; a declared endpoint sets some."""
        return {}

    @classmethod
    def _max_tokens_key(cls, agent_config: dict[str, Any]) -> str:
        """The name the server reads the output limit under.

        OpenAI refuses ``max_tokens`` on its reasoning models and takes
        ``max_completion_tokens`` on every model; another server at a ``base_url`` may
        know only ``max_tokens``.
        """
        return "max_tokens" if agent_config.get("base_url") else "max_completion_tokens"

    @classmethod
    def _generation_params(cls, agent_config: dict[str, Any]) -> dict[str, Any]:
        return extract_generation_params(
            agent_config,
            key_map={"max_tokens": cls._max_tokens_key(agent_config)},
            extra_params=("frequency_penalty", "presence_penalty"),
        )

    @classmethod
    def _no_answer(cls, message: Any, finish_reason: Any, model_name: str) -> NoAnswer | None:
        return chat_no_answer(
            message.content,
            finish_reason,
            message.refusal,
            vendor_label="OpenAI",
            model_name=model_name,
            vendor=cls.VENDOR,
        )

    @classmethod
    def call_json(
        cls,
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        from agent_actions.llm.providers.client_base import get_or_create_client

        client = get_or_create_client(OpenAI, api_key, **cls._client_options(agent_config))
        model_name: str = agent_config[MODEL_NAME_KEY]
        envelope = MessageBuilder.build(
            "openai",
            prompt_config,
            context_data,
            schema=schema,
            json_mode=True,
            model_name=model_name,
        )
        messages: list[ChatCompletionSystemMessageParam] = envelope.to_dicts()  # type: ignore[assignment]

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        fire_event(
            LLMRequestEvent(
                provider=cls.VENDOR,
                model=model_name,
                request_id=request_id,
            )
        )

        completion_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "response_format": (
                {"type": "json_schema", "json_schema": schema}
                if schema
                else {"type": "json_object"}
            ),
            **cls._generation_params(agent_config),
            # Per request, so it outranks a declared endpoint's client-wide timeout.
            **cls._request_timeout_kwargs(agent_config),
        }

        if request_headers := cls._request_headers():
            completion_kwargs["extra_headers"] = request_headers
        cls.VENDOR_PARAMS.apply(completion_kwargs, agent_config)
        start_time = time.perf_counter()
        try:
            response = client.chat.completions.create(**completion_kwargs)
        except openai.APIError as e:
            raise wrap_vendor_error(e, model_name, cls._error_mapping(), request_id) from e
        latency_ms = (time.perf_counter() - start_time) * 1000

        ResponseBuilder.record_usage_and_event(
            response, cls.VENDOR, model_name, latency_ms, request_id
        )

        response_message = response.choices[0].message
        response_content: str | None = response_message.content
        finish_reason = response.choices[0].finish_reason
        ended = cls._no_answer(response_message, finish_reason, model_name)
        if ended is not None:
            if response_content is not None:
                logger.warning("%s (model=%s)", ended.parse_error, model_name)
            elif response_message.refusal:
                fire_event(
                    LLMErrorEvent(
                        provider=cls.VENDOR,
                        model=model_name,
                        error_type="Refusal",
                        error_message=ended.parse_error,
                        request_id=request_id,
                    )
                )
                # The disposition keeps only the code parse_error; the run log carries the why.
                logger.warning("%s (model=%s)", ended.parse_error, model_name)
            else:
                fire_event(
                    LLMErrorEvent(
                        provider=cls.VENDOR,
                        model=model_name,
                        error_type="EmptyResponse",
                        error_message="Empty response content from OpenAI API",
                        request_id=request_id,
                    )
                )
                logger.debug(
                    "Empty response content from OpenAI API, model=%s",
                    model_name,
                )
            return [{"raw_response": "", "_parse_error": ended.parse_error}]
        assert response_content is not None  # no content is no answer, ended above
        if is_truncated(finish_reason):
            parse_error = cut_off_parse_error(finish_reason)
            logger.warning("%s (model=%s)", parse_error, model_name)
            return [{"raw_response": response_content, "_parse_error": parse_error}]
        from agent_actions.utils.json_parsing import parse_llm_json

        response_data = parse_llm_json(response_content)
        if isinstance(response_data, str):
            logger.debug(
                "Failed to parse JSON from OpenAI response (snippet: %.200s)",
                response_content,
                extra={"model": model_name, "operation": "call_json"},
            )
            fire_event(
                LLMErrorEvent(
                    provider=cls.VENDOR,
                    model=model_name,
                    error_type="JSONDecodeError",
                    error_message="Failed to parse JSON from response",
                    request_id=request_id,
                )
            )
            return [unparsed_json_record(response_content)]
        response_list: list[dict[str, Any]] = (
            response_data if isinstance(response_data, list) else [response_data]
        )
        return response_list

    @classmethod
    def call_non_json(
        cls,
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
    ) -> list[dict[str, str]]:
        from agent_actions.llm.providers.client_base import get_or_create_client

        client = get_or_create_client(OpenAI, api_key, **cls._client_options(agent_config))
        model_name: str = agent_config[MODEL_NAME_KEY]
        envelope = MessageBuilder.build("openai", prompt_config, context_data, json_mode=False)
        messages: list[ChatCompletionUserMessageParam] = envelope.to_dicts()  # type: ignore[assignment]

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        fire_event(
            LLMRequestEvent(
                provider=cls.VENDOR,
                model=model_name,
                request_id=request_id,
            )
        )

        completion_kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            **cls._generation_params(agent_config),
            # Per request, so it outranks a declared endpoint's client-wide timeout.
            **cls._request_timeout_kwargs(agent_config),
        }

        if request_headers := cls._request_headers():
            completion_kwargs["extra_headers"] = request_headers
        cls.VENDOR_PARAMS.apply(completion_kwargs, agent_config)
        start_time = time.perf_counter()
        try:
            response = client.chat.completions.create(**completion_kwargs)
        except openai.APIError as e:
            raise wrap_vendor_error(e, model_name, cls._error_mapping(), request_id) from e
        latency_ms = (time.perf_counter() - start_time) * 1000

        ResponseBuilder.record_usage_and_event(
            response, cls.VENDOR, model_name, latency_ms, request_id
        )

        response_message = response.choices[0].message
        content: str | None = response_message.content
        ended = cls._no_answer(response_message, response.choices[0].finish_reason, model_name)
        if ended is not None and ended.error is not None:
            error = ended.error
            fire_event(
                LLMErrorEvent(
                    provider=cls.VENDOR,
                    model=model_name,
                    error_type="EmptyResponse",
                    error_message=str(error),
                    request_id=request_id,
                )
            )
            raise error
        assert content is not None  # no content is no answer, raised above
        return ResponseBuilder.wrap_non_json(content, agent_config)
