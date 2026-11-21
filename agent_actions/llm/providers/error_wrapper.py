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
    QuotaExceededError,
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


# What a vendor's answer says when the account's quota, credit or balance is at its
# limit, which no wait clears, where the status alone does not say it: each answer is the
# statuses it comes with and the words it holds, every one of them. Lower case.
QUOTA_ANSWERS: dict[str, tuple[tuple[frozenset[int], tuple[str, ...]], ...]] = {
    "openai": ((frozenset({429, 403}), ("insufficient_quota",)),),
    "anthropic": ((frozenset({400}), ("invalid_request_error", "credit balance is too low")),),
    "ollama_cloud": (
        (frozenset({429, 403}), ("usage limit",)),
        (frozenset({429, 403}), ("usage credits",)),
    ),
}

_PAYMENT_REQUIRED = 402


def _status_code(e: BaseException) -> int | None:
    """The HTTP status an SDK error carries, wherever the SDK keeps it."""
    for holder, name in (
        (e, "status_code"),
        (e, "code"),
        (getattr(e, "response", None), "status_code"),
    ):
        status = getattr(holder, name, None)
        if isinstance(status, int) and not isinstance(status, bool):
            return status
    return None


def _error_words(e: BaseException, text: str) -> str:
    """The error's text with the code, type and body the SDK keeps beside it.

    Some SDK versions leave the error code (``insufficient_quota``) out of the message.
    """
    parts = [text]
    for name in ("code", "type", "body"):
        value = getattr(e, name, None)
        if value is not None and not isinstance(value, int):
            parts.append(str(value))
    return " ".join(parts)


def is_quota_answer(vendor: str, status_code: int | None, words: str) -> bool:
    """Whether an answer with this status and these words says the quota is at its limit."""
    if status_code == _PAYMENT_REQUIRED:
        return True
    lowered = words.lower()
    return any(
        status_code in statuses and all(word in lowered for word in needed)
        for statuses, needed in QUOTA_ANSWERS.get(vendor, ())
    )


def _says_quota_is_used_up(e: BaseException, text: str, vendor: str) -> bool:
    return is_quota_answer(vendor, _status_code(e), _error_words(e, text))


def _quota_error(
    text: str, vendor: str, model_name: str, cause: BaseException
) -> QuotaExceededError:
    return QuotaExceededError(
        f"{vendor} quota or billing stop: {text}",
        context={"vendor": vendor, "model": model_name, "provider_message": text},
        cause=cause if isinstance(cause, Exception) else None,
    )


def find_quota_error(e: BaseException, vendor: str) -> QuotaExceededError | None:
    """The quota or billing stop *e* is or was raised from, or None.

    Searches the cause chain: a batch client raises its own error with the SDK's as the cause.
    """
    seen: set[int] = set()
    current: BaseException | None = e
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, QuotaExceededError):
            return current
        text = _redact_sensitive_data(str(current))
        if _says_quota_is_used_up(current, text, vendor):
            return _quota_error(text, vendor, "", current)
        current = current.__cause__
    return None


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

    Fires appropriate LLM events (RateLimitEvent / LLMErrorEvent; none for a quota
    stop) and returns one of QuotaExceededError, RateLimitError, NetworkError, or
    VendorAPIError.

    Args:
        e: The vendor SDK exception.
        model_name: Model name for context/events.
        mapping: VendorErrorMapping describing how to classify this vendor's errors.
        request_id: Request correlation ID.

    Returns:
        A unified exception (QuotaExceededError, RateLimitError, NetworkError, or
        VendorAPIError), or the original exception if it doesn't match any known category.
    """
    vendor = mapping.vendor_name
    context: dict[str, object] = {"vendor": vendor, "model": model_name}
    # A server body can echo the request headers; masked by value and key shape only,
    # since the key-name rules would mangle the server's own text ("api_key: expected").
    text = _redact_sensitive_data(str(e))

    # --- Quota or billing stop, before the rate limit a 429 would otherwise read as ---
    # No event: the run it stops reports it once, where an event for each request in
    # flight would print the provider's answer once per record.
    if _says_quota_is_used_up(e, text, vendor):
        return _quota_error(text, vendor, model_name, e)

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
        # google-genai keeps it as .code, some SDKs on e.response
        status_code = _status_code(e)

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

    402 is a quota or billing stop, 429 a rate limit and any 5xx a network error, as the
    type-based mappings classify them (the SDKs' ``InternalServerError`` is every 5xx);
    any other status is an API error.
    """
    if status_code == _PAYMENT_REQUIRED:
        return QuotaExceededError(message, context={"provider_message": message})
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
