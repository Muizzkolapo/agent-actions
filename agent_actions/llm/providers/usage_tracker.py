"""
Async-safe token usage tracking for LLM providers.

Uses ``contextvars`` so each asyncio task (and each OS thread) gets its own
isolated copy of the usage counter.  ``threading.local`` only isolates by
thread — all asyncio tasks sharing an event-loop thread would see each
other's writes.
"""

from contextvars import ContextVar

# Context-local storage for token usage.
# Each asyncio task inherits a *copy* of the parent context, so concurrent
# tasks never overwrite each other's values.
_last_usage: ContextVar[dict[str, int] | None] = ContextVar("_last_usage", default=None)


def set_last_usage(usage: dict[str, int] | None) -> None:
    """
    Store token usage in the current context.

    This function is called by LLM providers after receiving API responses
    to store usage metadata. The data is context-local, so parallel
    executions (threads *and* asyncio tasks) don't interfere with each
    other.

    Args:
        usage: Dict with token count keys, or None to clear
               Expected keys: 'input_tokens', 'output_tokens', 'total_tokens'
    """
    _last_usage.set(usage)


def get_last_usage() -> dict[str, int] | None:
    """
    Retrieve token usage from the current context.

    This function is called by ActionExecutor after provider invocation
    to retrieve token usage for tracking purposes. Returns None for
    providers that don't track usage.

    Returns:
        Usage dict with token counts, or None if not set
    """
    return _last_usage.get()


def clear_usage() -> None:
    """
    Clear usage data from the current context.

    Primarily useful for testing to ensure clean state between tests.
    """
    _last_usage.set(None)
