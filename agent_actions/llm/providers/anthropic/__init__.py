from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_actions.prompt.message_builder import LLMMessageEnvelope

PROMPT_CACHING_BETA_HEADER = {"anthropic-beta": "prompt-caching-2024-07-31"}

# The most `cache_control` marks the Messages API takes in one request.
MAX_CACHE_BREAKPOINTS = 4

_SERVER_BUSY_ERROR_NAMES = ("OverloadedError", "ServiceUnavailableError", "DeadlineExceededError")


def server_busy_errors(anthropic: Any) -> tuple[type[Exception], ...]:
    """The SDK's errors for a server that cannot answer now, outside InternalServerError.

    The SDK raises 529 (overloaded) as OverloadedError, and 503 and 504 from some
    platforms as ServiceUnavailableError and DeadlineExceededError: APIStatusErrors that
    are not InternalServerErrors. Not every SDK version defines or exports them.
    """
    found = []
    for name in _SERVER_BUSY_ERROR_NAMES:
        error = getattr(anthropic, name, None) or getattr(anthropic._exceptions, name, None)
        if error is not None:
            found.append(error)
    return tuple(found)


def message_params(envelope: LLMMessageEnvelope) -> list[dict[str, Any]]:
    """The envelope's messages as the Messages API takes them, online or on a batch line.

    A message with cache boundaries goes as text blocks, each boundary ending a block
    that carries a `cache_control` mark; the blocks hold the text the message holds.
    """
    params: list[dict[str, Any]] = []
    marks = 0
    for message in envelope.messages:
        if not message.cache_boundaries:
            params.append({"role": message.role, "content": message.content})
            continue
        blocks: list[dict[str, Any]] = []
        for text, cached in message.segments():
            block: dict[str, Any] = {"type": "text", "text": text}
            if cached:
                block["cache_control"] = {"type": "ephemeral"}
            blocks.append(block)
        marks += len(message.cache_boundaries)
        params.append({"role": message.role, "content": blocks})
    if marks > MAX_CACHE_BREAKPOINTS:
        raise ValueError(
            f"The prompt rendered {marks} cache boundaries; Anthropic takes at most "
            f"{MAX_CACHE_BREAKPOINTS} cache breakpoints in a request"
        )
    return params
