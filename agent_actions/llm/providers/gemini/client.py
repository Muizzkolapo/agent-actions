"""
Gemini client for agent-actions LLM invocation.

Provides implementation of call_json() and call_non_json() methods
for Google Gemini API integration.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import logging
import math
import time
import uuid
from enum import Enum
from typing import Any, ClassVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from agent_actions.errors import NetworkError, RateLimitError, VendorAPIError
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import (
    TRANSPORT_ERRORS,
    NoAnswer,
    VendorErrorMapping,
    empty_parse_error,
    empty_response_error,
    stop_reason_name,
    unfinished_parse_error,
    wrap_vendor_error,
)
from agent_actions.llm.providers.generation_params import (
    ALWAYS_RESERVED,
    VendorParamSpec,
    extract_generation_params,
    request_timeout_seconds,
)
from agent_actions.llm.providers.mixins import (
    GenericErrorHandlerMixin,
    JSONResponseMixin,
)
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    LLMErrorEvent,
    LLMRequestEvent,
)
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.prompt.message_builder import MessageBuilder
from agent_actions.utils.constants import MODEL_NAME_KEY

logger = logging.getLogger(__name__)


_ERROR_MAPPING = VendorErrorMapping(
    vendor_name="gemini",
    status_code_error_types=(genai_errors.ClientError, genai_errors.ServerError),
    base_api_error_type=genai_errors.APIError,
    supports_retry_after=False,
)


def _build_client(api_key: str) -> genai.Client:
    """Build a google-genai Client instance."""
    return genai.Client(api_key=api_key)


def _reason_name(reason: Any) -> str | None:
    """A block or finish reason as text; None when the response sets none."""
    return stop_reason_name(reason) if isinstance(reason, str | Enum) else None


def no_answer(block_reason: Any, finish_reason: Any, model_name: str) -> NoAnswer:
    """How a response with no text ends, read alike from an SDK response and a batch line.

    A blocked prompt and a stop that is not the model's own are errors naming the reason.
    An answer the model ended with nothing in it is left to the action's ``on_empty``.
    """
    context = {"model_name": model_name, "vendor": "gemini", "api_operation": "generate_content"}
    block = _reason_name(block_reason)
    if block:
        message = f"Gemini blocked the prompt (blockReason={block})"
        return NoAnswer(parse_error=message, error=VendorAPIError(message, context=context))
    reason = _reason_name(finish_reason)
    if reason is None or reason == "STOP":
        return NoAnswer(parse_error=empty_parse_error(reason))
    return NoAnswer(
        parse_error=empty_parse_error(reason),
        error=empty_response_error(
            "Gemini", reason, model_name=model_name, vendor="gemini", operation="generate_content"
        ),
    )


def _finish_reason(response: Any) -> Any:
    candidates = getattr(response, "candidates", None) or []
    return getattr(candidates[0], "finish_reason", None) if candidates else None


def _no_answer_in(response: Any, model_name: str) -> NoAnswer:
    block_reason = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
    return no_answer(block_reason, _finish_reason(response), model_name)


def _timeout_options(agent_config: dict[str, Any]) -> dict[str, Any]:
    """The action's request timeout as per-request http_options; google-genai takes ms."""
    timeout = request_timeout_seconds(agent_config)
    return {"http_options": types.HttpOptions(timeout=math.ceil(timeout * 1000))}


class GeminiClient(BaseClient, JSONResponseMixin, GenericErrorHandlerMixin):
    """Google Gemini API client for JSON and non-JSON LLM invocations."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "temperature", "max_tokens"],
    }
    # Gemini takes its generation settings in GenerateContentConfig, so these are its fields.
    VENDOR_PARAMS: ClassVar[VendorParamSpec] = VendorParamSpec(
        accepted=frozenset(types.GenerateContentConfig.model_fields),
        reserved=ALWAYS_RESERVED | {"http_options"},
    )

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        # Fire LLM request event
        fire_event(
            LLMRequestEvent(
                provider="gemini",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = time.perf_counter()
        try:
            client = _build_client(api_key)
            gen_params = extract_generation_params(
                agent_config,
                key_map={"max_tokens": "max_output_tokens", "stop": "stop_sequences"},
                stop_as_list=True,
            )
            config = types.GenerateContentConfig(
                **GeminiClient.VENDOR_PARAMS.apply(
                    {
                        "response_mime_type": "application/json",
                        **gen_params,
                        **_timeout_options(agent_config),
                    },
                    agent_config,
                )
            )
            envelope = MessageBuilder.build(
                "gemini",
                prompt_config,
                context_data,
                schema=schema,
                json_mode=True,
                context_window=agent_config.get("context_window"),
            )
            response_temp = client.models.generate_content(
                model=model_name, contents=envelope.prompt_body, config=config
            )
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except genai_errors.APIError as e:
            raise wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id) from e
        except TRANSPORT_ERRORS as e:
            raise wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id) from e
        except Exception as e:
            fire_event(
                LLMErrorEvent(
                    provider="gemini",
                    model=model_name,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            GeminiClient.handle_generic_error(e, "Gemini", "call_json", model_name)

        latency_ms = (time.perf_counter() - start_time) * 1000

        ResponseBuilder.record_usage_and_event(
            response_temp, "gemini", model_name, latency_ms, request_id
        )

        response_text = response_temp.text or ""
        if not response_text:
            parse_error = _no_answer_in(response_temp, model_name).parse_error
            logger.warning("Gemini model=%s: %s", model_name, parse_error)
            return [{"raw_response": "", "_parse_error": parse_error}]
        finish_reason = _finish_reason(response_temp)
        unfinished = unfinished_parse_error(finish_reason)
        if unfinished:
            logger.warning("Gemini model=%s: %s", model_name, unfinished)
            return [{"raw_response": response_text, "_parse_error": unfinished}]
        result = GeminiClient.parse_json_response(
            response_content=response_text,
            vendor_name="Gemini",
            operation="call_json",
            model_name=model_name,
        )
        return result if isinstance(result, list) else [result]

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        model_name = agent_config[MODEL_NAME_KEY]

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        # Fire LLM request event
        fire_event(
            LLMRequestEvent(
                provider="gemini",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = time.perf_counter()
        try:
            client = _build_client(api_key)
            gen_params = extract_generation_params(
                agent_config,
                key_map={"max_tokens": "max_output_tokens", "stop": "stop_sequences"},
                stop_as_list=True,
            )
            config = types.GenerateContentConfig(
                **GeminiClient.VENDOR_PARAMS.apply(
                    {**gen_params, **_timeout_options(agent_config)}, agent_config
                )
            )
            envelope = MessageBuilder.build(
                "gemini",
                prompt_config,
                context_data,
                json_mode=False,
                context_window=agent_config.get("context_window"),
            )
            response_temp = client.models.generate_content(
                model=model_name, contents=envelope.prompt_body, config=config
            )
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except genai_errors.APIError as e:
            raise wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id) from e
        except TRANSPORT_ERRORS as e:
            raise wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id) from e
        except Exception as e:
            fire_event(
                LLMErrorEvent(
                    provider="gemini",
                    model=model_name,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            logger.exception(
                "Gemini non-JSON API call failed",
                extra={
                    "operation": "gemini_call_non_json",
                    "model": model_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "request_id": request_id,
                },
            )
            raise VendorAPIError(
                f"Gemini non-JSON API call failed: {e}",
                vendor="gemini",
                cause=e,
            ) from e

        latency_ms = (time.perf_counter() - start_time) * 1000

        ResponseBuilder.record_usage_and_event(
            response_temp, "gemini", model_name, latency_ms, request_id
        )

        response_text = response_temp.text or ""
        if not response_text:
            unanswered = _no_answer_in(response_temp, model_name)
            if unanswered.error is not None:
                raise unanswered.error
            return []

        logger.debug(
            "Gemini non-JSON response retrieved successfully",
            extra={
                "operation": "gemini_call_non_json",
                "model": model_name,
                "response_length": len(response_text) if response_text else 0,
                "request_id": request_id,
            },
        )
        return ResponseBuilder.wrap_non_json(response_text, agent_config)
