from typing import Any

PROMPT_CACHING_BETA_HEADER = {"anthropic-beta": "prompt-caching-2024-07-31"}

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
