"""Unified vendor error wrapping for all LLM providers.

Consolidates the identical _wrap_<vendor>_error() functions that were
duplicated across 7 provider clients into a single shared utility.

Each provider defines a VendorErrorMapping that tells wrap_vendor_error()
how to classify vendor-specific exception types into our unified error hierarchy.
"""

import logging
from dataclasses import dataclass

from agent_actions.errors import NetworkError, RateLimitError, VendorAPIError
from agent_actions.logging import fire_event
from agent_actions.logging.events import LLMErrorEvent, RateLimitEvent

logger = logging.getLogger(__name__)


def _extract_retry_after(e: Exception) -> float | None:
    """Extract retry-after header from an API error response.

    Works with OpenAI, Anthropic, and Groq SDKs that expose
    `response.headers` on their exception objects.

    Args:
        e: The API exception with potential response headers

    Returns:
        Parsed retry-after value as float, or None if not available
    """
    if not hasattr(e, "response") or not e.response:
        return None
    retry_after = e.response.headers.get("retry-after")
    if not retry_after:
        return None
    try:
        return float(retry_after)
    except ValueError:
        return None


@dataclass(frozen=True)
class VendorErrorMapping:
    """Maps vendor SDK exception types to unified error categories.

    Supports two classification strategies:
    1. **Type-based** (OpenAI, Anthropic, Groq): specific exception classes
       for rate-limit, connection, timeout, server-error, and base API error.
    2. **Status-code-based** (Cohere, Gemini, Mistral, Ollama-HTTP): a single SDK error
       type with a `.status_code` or `.code` attribute inspected at runtime.

    Attributes:
        vendor_name: Human-readable vendor name for error messages and events.
        rate_limit_types: Exception types indicating rate limiting.
        network_error_types: Exception types indicating connection/timeout/server errors.
        base_api_error_type: Catch-all vendor API error base type.
        status_code_error_types: Exception types that carry a `.status_code` or `.code` attribute.
        extra_network_types: Additional Python-builtin or httpx types treated as network errors.
        supports_retry_after: Whether retry-after header extraction should be attempted.
    """

    vendor_name: str
    rate_limit_types: tuple[type[Exception], ...] = ()
    network_error_types: tuple[type[Exception], ...] = ()
    base_api_error_type: type[Exception] | None = None
    status_code_error_types: tuple[type[Exception], ...] = ()
    extra_network_types: tuple[type[Exception], ...] = ()
    supports_retry_after: bool = False


def wrap_vendor_error(
    e: Exception,
    model_name: str,
    mapping: VendorErrorMapping,
    request_id: str = "",
) -> Exception:
    """Wrap a vendor SDK exception into a unified agent-actions error type.

    Fires appropriate LLM events (RateLimitEvent / LLMErrorEvent) and returns
    one of RateLimitError, NetworkError, or VendorAPIError.

    Args:
        e: The vendor SDK exception.
        model_name: Model name for context/events.
        mapping: VendorErrorMapping describing how to classify this vendor's errors.
        request_id: Request correlation ID.

    Returns:
        A unified exception (RateLimitError, NetworkError, or VendorAPIError),
        or the original exception if it doesn't match any known category.
    """
    vendor = mapping.vendor_name
    context: dict[str, object] = {"vendor": vendor, "model": model_name}

    # --- Type-based rate-limit detection ---
    if mapping.rate_limit_types and isinstance(e, mapping.rate_limit_types):
        retry_after = _extract_retry_after(e) if mapping.supports_retry_after else None
        context["retry_after"] = retry_after
        fire_event(
            RateLimitEvent(
                provider=vendor,
                retry_after=retry_after or 0.0,
                request_id=request_id,
            )
        )
        return RateLimitError(f"{vendor} rate limit: {e}", context=context, cause=e)

    # --- Type-based network-error detection ---
    if mapping.network_error_types and isinstance(e, mapping.network_error_types):
        error_type = type(e).__name__
        fire_event(
            LLMErrorEvent(
                provider=vendor,
                model=model_name,
                error_type=error_type,
                error_message=str(e),
                request_id=request_id,
            )
        )
        return NetworkError(f"{vendor} network error: {e}", context=context, cause=e)

    # --- Status-code-based classification (Cohere, Mistral, Ollama HTTP) ---
    if mapping.status_code_error_types and isinstance(e, mapping.status_code_error_types):
        status_code = getattr(e, "status_code", None)
        # google-genai uses .code instead of .status_code
        if status_code is None:
            status_code = getattr(e, "code", None)
        # Some SDKs put status_code on e.response
        if status_code is None and hasattr(e, "response"):
            status_code = getattr(e.response, "status_code", None)

        if status_code == 429:
            context["retry_after"] = None
            fire_event(
                RateLimitEvent(
                    provider=vendor,
                    retry_after=0.0,
                    request_id=request_id,
                )
            )
            return RateLimitError(f"{vendor} rate limit: {e}", context=context, cause=e)

        if status_code in (500, 502, 503, 504):
            fire_event(
                LLMErrorEvent(
                    provider=vendor,
                    model=model_name,
                    error_type=f"HTTP{status_code}",
                    error_message=str(e),
                    request_id=request_id,
                )
            )
            return NetworkError(
                f"{vendor} server error ({status_code}): {e}", context=context, cause=e
            )

        # Other status codes → VendorAPIError
        fire_event(
            LLMErrorEvent(
                provider=vendor,
                model=model_name,
                error_type=type(e).__name__,
                error_message=str(e),
                request_id=request_id,
            )
        )
        return VendorAPIError(f"{vendor} API error: {e}", context=context, cause=e)

    # --- Extra network types (Python builtins, httpx) ---
    if mapping.extra_network_types and isinstance(e, mapping.extra_network_types):
        fire_event(
            LLMErrorEvent(
                provider=vendor,
                model=model_name,
                error_type=type(e).__name__,
                error_message=str(e),
                request_id=request_id,
            )
        )
        return NetworkError(f"{vendor} network error: {e}", context=context, cause=e)

    # --- Catch-all base API error type ---
    if mapping.base_api_error_type and isinstance(e, mapping.base_api_error_type):
        fire_event(
            LLMErrorEvent(
                provider=vendor,
                model=model_name,
                error_type="APIError",
                error_message=str(e),
                request_id=request_id,
            )
        )
        return VendorAPIError(f"{vendor} API error: {e}", context=context, cause=e)

    # Unknown exception type — return as-is for caller to handle
    return e
