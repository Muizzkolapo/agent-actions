"""
Mistral client for agent-actions LLM invocation.

Provides implementation of call_json() and call_non_json() methods
for Mistral API integration.

SDK errors are wrapped into unified agent-actions error types to enable
consistent retry handling across all providers.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, ClassVar

from agent_actions.errors import DependencyError, NetworkError, RateLimitError, VendorAPIError
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.generation_params import extract_generation_params
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

# Optional SDK imports. Keep module import-safe so non-mistral users (and CI)
# can still import the client registry/capabilities without installing mistralai.
MistralSDK: Any | None = None
mistral_models: Any
try:
    from mistralai import Mistral as _MistralSDK  # type: ignore[import-not-found]
    from mistralai import models as _mistral_models  # type: ignore[import-not-found]

    MistralSDK = _MistralSDK
    mistral_models = _mistral_models
except Exception:  # pragma: no cover
    MistralSDK = None

    class _MistralModelsFallback:
        SDKError = Exception

    mistral_models = _MistralModelsFallback()

# Backwards-compatible alias for tests/patches that expect this symbol.
Mistral = MistralSDK


_ERROR_MAPPING = VendorErrorMapping(
    vendor_name="mistral",
    status_code_error_types=(mistral_models.SDKError,),
    extra_network_types=(ConnectionError, TimeoutError),
    supports_retry_after=False,
)


def _wrap_mistral_error(e: Exception, model_name: str, request_id: str = "") -> Exception:
    """Wrap Mistral SDK errors into unified agent-actions error types."""
    return wrap_vendor_error(e, model_name, _ERROR_MAPPING, request_id)


class MistralClient(BaseClient, JSONResponseMixin, GenericErrorHandlerMixin):
    """Mistral AI API client for JSON and non-JSON LLM invocations."""

    CAPABILITIES: ClassVar[dict[str, Any]] = {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": False,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "temperature", "max_tokens"],
    }

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        model_name = agent_config[MODEL_NAME_KEY]

        # Generate request ID for correlation
        request_id = str(uuid.uuid4())

        # Fire LLM request event
        fire_event(
            LLMRequestEvent(
                provider="mistral",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = datetime.now()
        try:
            if Mistral is None:  # pragma: no cover
                raise DependencyError(
                    "Mistral SDK is not installed (or is incompatible).",
                    context={
                        "vendor": "mistral",
                        "package": "mistralai",
                        "install_command": "uv pip install mistralai",
                    },
                )
            client = Mistral(api_key=api_key)
            envelope = MessageBuilder.build(
                "mistral", prompt_config, context_data, schema=schema, json_mode=True
            )
            messages = envelope.to_dicts()
            json_kwargs = {
                "model": model_name,
                "response_format": (
                    {"type": "json_schema", "json_schema": schema}
                    if schema
                    else {"type": "json_object"}
                ),
                "messages": messages,
                **extract_generation_params(
                    agent_config, extra_params=("frequency_penalty", "presence_penalty")
                ),
            }
            chat_response = client.chat.complete(**json_kwargs)
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except mistral_models.SDKError as e:
            raise _wrap_mistral_error(e, model_name, request_id) from e
        except Exception as e:
            fire_event(
                LLMErrorEvent(
                    provider="mistral",
                    model=model_name,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            MistralClient.handle_generic_error(e, "Mistral", "call_json", model_name)

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        ResponseBuilder.record_usage_and_event(
            chat_response, "mistral", model_name, latency_ms, request_id
        )

        response_content = chat_response.choices[0].message.content

        result = MistralClient.parse_json_response(
            response_content=response_content,  # type: ignore[arg-type]
            vendor_name="Mistral",
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
                provider="mistral",
                model=model_name,
                request_id=request_id,
            )
        )

        start_time = datetime.now()
        try:
            if Mistral is None:  # pragma: no cover
                raise DependencyError(
                    "Mistral SDK is not installed (or is incompatible).",
                    context={
                        "vendor": "mistral",
                        "package": "mistralai",
                        "install_command": "uv pip install mistralai",
                    },
                )
            client = Mistral(api_key=api_key)
            envelope = MessageBuilder.build("mistral", prompt_config, context_data, json_mode=False)
            messages = envelope.to_dicts()
            non_json_kwargs = {
                "model": model_name,
                "messages": messages,
                **extract_generation_params(
                    agent_config, extra_params=("frequency_penalty", "presence_penalty")
                ),
            }
            chat_response = client.chat.complete(**non_json_kwargs)
        except (RateLimitError, NetworkError, VendorAPIError):
            raise
        except mistral_models.SDKError as e:
            raise _wrap_mistral_error(e, model_name, request_id) from e
        except Exception as e:
            fire_event(
                LLMErrorEvent(
                    provider="mistral",
                    model=model_name,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            logger.exception(
                "Mistral non-JSON API call failed",
                extra={
                    "operation": "mistral_call_non_json",
                    "model": model_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "request_id": request_id,
                },
            )
            raise VendorAPIError(
                f"Mistral non-JSON API call failed: {e}",
                vendor="mistral",
                cause=e,
            ) from e

        duration = (datetime.now() - start_time).total_seconds()
        latency_ms = duration * 1000

        ResponseBuilder.record_usage_and_event(
            chat_response, "mistral", model_name, latency_ms, request_id
        )

        response_output = chat_response.choices[0].message.content
        if response_output is None:
            raise VendorAPIError(
                "Mistral API returned null content",
                context={
                    "model_name": model_name,
                    "vendor": "mistral",
                    "api_operation": "chat.complete",
                },
            )
        if not isinstance(response_output, str):
            content_type = type(response_output).__name__
            raise VendorAPIError(
                f"Mistral API returned non-string content: {content_type}",
                context={
                    "model_name": model_name,
                    "vendor": "mistral",
                    "api_operation": "chat.complete",
                    "content_type": content_type,
                },
            )
        logger.debug(
            "Mistral non-JSON response retrieved successfully",
            extra={
                "operation": "mistral_call_non_json",
                "model": model_name,
                "response_length": len(response_output) if response_output else 0,
                "request_id": request_id,
            },
        )
        return ResponseBuilder.wrap_non_json(response_output, agent_config)
