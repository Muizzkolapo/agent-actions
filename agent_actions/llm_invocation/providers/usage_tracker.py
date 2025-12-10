"""
Thread-safe token usage tracking for LLM providers.

Providers that support token usage reporting (OpenAI, Anthropic) store
usage data in thread-local storage after API calls. AgentExecutor retrieves
this data to track token consumption per action.

Thread-local storage ensures no cross-contamination in parallel execution.
Each thread maintains its own usage data, preventing race conditions when
multiple agents run concurrently.

Usage Pattern:
    In provider (OpenAI, Anthropic):
        usage_data = {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150}
        set_last_usage(usage_data)

    In orchestration (AgentExecutor):
        tokens = get_last_usage()  # Returns usage dict or None
        if tokens:
            track_action_tokens(tokens)
"""
import threading
from typing import Dict, Optional

# Thread-local storage for token usage
_thread_local = threading.local()


def set_last_usage(usage: Optional[Dict[str, int]]) -> None:
    """
    Store token usage in thread-local storage.

    This function is called by LLM providers after receiving API responses
    to store usage metadata. The data is thread-local, so parallel executions
    don't interfere with each other.

    Args:
        usage: Dict with token count keys, or None to clear
               Expected keys: 'input_tokens', 'output_tokens', 'total_tokens'

    Example:
        # OpenAI provider
        if response.usage:
            usage_data = {
                'input_tokens': response.usage.prompt_tokens,
                'output_tokens': response.usage.completion_tokens,
                'total_tokens': response.usage.total_tokens
            }
            set_last_usage(usage_data)
    """
    _thread_local.last_usage = usage


def get_last_usage() -> Optional[Dict[str, int]]:
    """
    Retrieve token usage from thread-local storage.

    This function is called by AgentExecutor after provider invocation
    to retrieve token usage for tracking purposes. Returns None for
    providers that don't track usage (Gemini, Ollama, Groq, etc.).

    Returns:
        Usage dict with token counts, or None if not set

    Example:
        # AgentExecutor
        tokens = get_last_usage()
        if tokens:
            self.run_tracker.record_action_complete(
                run_id, action_name, 'success',
                tokens=tokens
            )
    """
    return getattr(_thread_local, 'last_usage', None)


def clear_usage() -> None:
    """
    Clear usage data from thread-local storage.

    Primarily useful for testing to ensure clean state between tests.
    Not typically needed in production code as each action naturally
    overwrites the previous usage.

    Example:
        # In test setup
        clear_usage()
        # Run test
        # Verify results
    """
    if hasattr(_thread_local, 'last_usage'):
        delattr(_thread_local, 'last_usage')
