"""Unified vendor error wrapping for all LLM providers.

Consolidates the identical _wrap_<vendor>_error() functions that were
duplicated across 7 provider clients into a single shared utility.

Each provider defines a VendorErrorMapping that tells wrap_vendor_error()
how to classify vendor-specific exception types into our unified error hierarchy.
"""

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Any

import httpx

from agent_actions.errors import (
    NetworkError,
    RateLimitError,
    ResponseTruncatedError,
    VendorAPIError,
)
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import LLMErrorEvent, RateLimitEvent
from agent_actions.logging.filters import _redact_sensitive_data

logger = logging.getLogger(__name__)

# A request that never got an answer: the connection was refused, dropped, reset or
# timed out. Every mapping wraps them as NetworkError. The clients whose SDKs let them
# through (gemini, cohere: raw httpx) or re-raise them as builtins (ollama:
# ConnectionError for httpx.ConnectError) catch them; openai, anthropic and groq
# already turn them into their own APIConnectionError.
TRANSPORT_ERRORS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    httpx.NetworkError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
)


def _extract_retry_after(e: Exception) -> float | None:
    """Seconds the provider asked to wait, from the error's response headers; None if unreadable.

    Reads `retry-after-ms`, then `retry-after` as seconds or as an HTTP date. A wait in the
    past is 0; a value that is not a number (`nan` included) is unreadable. Works with SDKs that expose `response.headers` (OpenAI, Anthropic, Groq).
    """
    if not hasattr(e, "response") or not e.response:
        return None
    headers = e.response.headers
    milliseconds = headers.get("retry-after-ms")
    if milliseconds:
        try:
            seconds = float(milliseconds) / 1000
        except ValueError:
            seconds = math.nan
        if not math.isnan(seconds):
            return max(seconds, 0.0)
    retry_after = headers.get("retry-after")
    if not retry_after:
        return None
    try:
        seconds = float(retry_after)
    except ValueError:
        seconds = math.nan
    if not math.isnan(seconds):
        return max(seconds, 0.0)
    try:
        when = parsedate_to_datetime(str(retry_after))
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - datetime.now(UTC)).total_seconds(), 0.0)


@dataclass(frozen=True)
class VendorErrorMapping:
    """Maps vendor SDK exception types to unified error categories.

    Supports two classification strategies:
    1. **Type-based** (OpenAI, Anthropic, Groq): specific exception classes
       for rate-limit, connection, timeout, server-error, and base API error.
    2. **Status-code-based** (Cohere, Gemini, Ollama-HTTP): a single SDK error
       type with a `.status_code` or `.code` attribute inspected at runtime.

    Attributes:
        vendor_name: Human-readable vendor name for error messages and events.
        rate_limit_types: Exception types indicating rate limiting.
        network_error_types: Exception types indicating connection/timeout/server errors.
        base_api_error_type: Catch-all vendor API error base type.
        status_code_error_types: Exception types that carry a `.status_code` or `.code` attribute.
        extra_network_types: Network error types beyond ``TRANSPORT_ERRORS``, which every
            mapping treats as network errors.
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
    # A server body can echo the request headers; masked by value and key shape only,
    # since the key-name rules would mangle the server's own text ("api_key: expected").
    text = _redact_sensitive_data(str(e))

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
        return RateLimitError(f"{vendor} rate limit: {text}", context=context, cause=e)

    # --- Type-based network-error detection ---
    if mapping.network_error_types and isinstance(e, mapping.network_error_types):
        error_type = type(e).__name__
        fire_event(
            LLMErrorEvent(
                provider=vendor,
                model=model_name,
                error_type=error_type,
                error_message=text,
                request_id=request_id,
            )
        )
        return NetworkError(f"{vendor} network error: {text}", context=context, cause=e)

    # --- Status-code-based classification (Cohere, Ollama HTTP) ---
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
            return RateLimitError(f"{vendor} rate limit: {text}", context=context, cause=e)

        if status_code in (500, 502, 503, 504):
            fire_event(
                LLMErrorEvent(
                    provider=vendor,
                    model=model_name,
                    error_type=f"HTTP{status_code}",
                    error_message=text,
                    request_id=request_id,
                )
            )
            return NetworkError(
                f"{vendor} server error ({status_code}): {text}", context=context, cause=e
            )

        # Other status codes → VendorAPIError
        fire_event(
            LLMErrorEvent(
                provider=vendor,
                model=model_name,
                error_type=type(e).__name__,
                error_message=text,
                request_id=request_id,
            )
        )
        return VendorAPIError(f"{vendor} API error: {text}", context=context, cause=e)

    # --- Transport failures and extra network types (Python builtins, httpx) ---
    if isinstance(e, TRANSPORT_ERRORS + mapping.extra_network_types):
        fire_event(
            LLMErrorEvent(
                provider=vendor,
                model=model_name,
                error_type=type(e).__name__,
                error_message=text,
                request_id=request_id,
            )
        )
        return NetworkError(f"{vendor} network error: {text}", context=context, cause=e)

    # --- Catch-all base API error type ---
    if mapping.base_api_error_type and isinstance(e, mapping.base_api_error_type):
        fire_event(
            LLMErrorEvent(
                provider=vendor,
                model=model_name,
                error_type="APIError",
                error_message=text,
                request_id=request_id,
            )
        )
        return VendorAPIError(f"{vendor} API error: {text}", context=context, cause=e)

    # Unknown exception type — return as-is for caller to handle
    return e


def error_for_status(status_code: int, message: str) -> VendorAPIError | NetworkError:
    """The error online raises for an answer with *status_code*, for a caller that has no exception.

    429 is a rate limit and any 5xx a network error, as the type-based mappings classify
    them (the SDKs' ``InternalServerError`` is every 5xx); any other status is an API error.
    """
    if status_code == 429:
        return RateLimitError(message)
    if status_code >= 500:
        return NetworkError(message)
    return VendorAPIError(message)


# Each vendor's word for "the output budget ran out" (Gemini and Cohere write it in capitals).
_TRUNCATED_STOP_REASONS = frozenset({"max_tokens", "length"})


def stop_reason_name(reason: Any) -> str | None:
    """A vendor's stop or finish reason as plain text; an enum by its value."""
    if reason is None:
        return None
    if isinstance(reason, Enum):
        reason = reason.value
    return str(reason)


def is_truncated(reason: Any) -> bool:
    """Whether the model stopped because the output budget ran out."""
    name = stop_reason_name(reason)
    return name is not None and name.lower() in _TRUNCATED_STOP_REASONS


# Stops the provider made, not the model: a content filter, a safety or recitation block, a refusal.
_PROVIDER_STOP_REASONS = frozenset({"content_filter", "safety", "recitation", "refusal"})


def is_stopped_by_provider(reason: Any) -> bool:
    """Whether a filter or a block, not the model, ended the answer."""
    name = stop_reason_name(reason)
    return name is not None and name.lower() in _PROVIDER_STOP_REASONS


def is_unfinished(reason: Any) -> bool:
    """Whether the answer ended before the model finished it: cut off, or stopped by the provider."""
    return is_truncated(reason) or is_stopped_by_provider(reason)


def refusal_text(refusal: str) -> str:
    """The error for an answer the model declined to give, quoting its reason."""
    return f"The model refused to answer: {refusal}"


def empty_parse_error(stop_reason: Any) -> str:
    """The parse error for a JSON-mode response that holds no text, naming why the model stopped."""
    return f"Empty response from API (stop_reason={stop_reason_name(stop_reason)})"


def unparsed_json_record(text: str) -> dict[str, str]:
    """What JSON mode stores for an answer no parse could read, online or in a batch."""
    return {"raw_response": text, "_parse_error": "Failed to parse JSON from LLM response"}


def cut_off_parse_error(stop_reason: Any) -> str:
    """The parse error for a JSON answer the output limit stopped.

    Reading it would mean guessing its end, so it is never repaired into an object.
    """
    return (
        f"The answer was cut off at the output limit (stop_reason={stop_reason_name(stop_reason)})"
        "; raise max_tokens"
    )


def stopped_parse_error(stop_reason: Any) -> str:
    """The parse error for a JSON answer that a filter or a block stopped partway."""
    return (
        f"The provider stopped the answer before its end (stop_reason={stop_reason_name(stop_reason)})"
        "; the answer is not complete"
    )


def unfinished_parse_error(stop_reason: Any) -> str | None:
    """The parse error for a JSON answer that ended before the model finished it; None otherwise."""
    if is_truncated(stop_reason):
        return cut_off_parse_error(stop_reason)
    if is_stopped_by_provider(stop_reason):
        return stopped_parse_error(stop_reason)
    return None


@dataclass(frozen=True)
class NoAnswer:
    """A response that holds no answer, as each mode of a client ends it.

    ``parse_error`` is the ``_parse_error`` a JSON-mode call stores. ``error`` is what a
    text-mode call raises; None hands the empty answer to the action's ``on_empty``.
    """

    parse_error: str
    error: VendorAPIError | None = None

    @property
    def retried(self) -> bool | None:
        """Whether the retry policy retries ``error``; None when there is none to retry."""
        from agent_actions.processing.recovery.retry import is_retriable_error

        return is_retriable_error(self.error) if self.error is not None else None


def empty_response_error(
    vendor_label: str, stop_reason: Any, *, model_name: str, vendor: str, operation: str
) -> VendorAPIError:
    """The error for a response that holds no answer, naming why the model stopped.

    A stop at the output limit is a ``ResponseTruncatedError``, which the retry policy retries.
    """
    reason = stop_reason_name(stop_reason)
    message = f"Empty response content from {vendor_label} API (stop_reason={reason})"
    context = {
        "model_name": model_name,
        "vendor": vendor,
        "api_operation": operation,
        "stop_reason": reason,
    }
    if is_truncated(reason):
        return ResponseTruncatedError(
            f"{message}: the output budget ran out before any answer; raise max_tokens, "
            "or lower the thinking budget in vendor_params",
            context=context,
        )
    return VendorAPIError(message, context=context)


def chat_no_answer(
    content: Any,
    finish_reason: Any,
    refusal: Any,
    *,
    vendor_label: str,
    model_name: str,
    vendor: str,
    operation: str = "chat.completions.create",
) -> NoAnswer | None:
    """How a chat-completions message with no answer ends, online or in a batch.

    None when it holds one. No answer is no content, or content the output limit
    stopped before its first character. A refusal ends with the model's reason.
    """
    cut_off_at_once = content == "" and is_truncated(finish_reason)
    if content is not None and not cut_off_at_once:
        return None
    if cut_off_at_once:
        parse_error = cut_off_parse_error(finish_reason)
    elif refusal:
        parse_error = refusal_text(refusal)
    else:
        parse_error = empty_parse_error(finish_reason)
    if refusal:
        return NoAnswer(
            parse_error=parse_error,
            error=VendorAPIError(
                refusal_text(refusal),
                context={"model_name": model_name, "vendor": vendor, "api_operation": operation},
            ),
        )
    return NoAnswer(
        parse_error=parse_error,
        error=empty_response_error(
            vendor_label, finish_reason, model_name=model_name, vendor=vendor, operation=operation
        ),
    )
