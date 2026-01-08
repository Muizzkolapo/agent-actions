"""Client invocation service for agent builder.

Handles client routing, invocation, and retry for transient errors.
Supports retry event tracking for debugging and analysis.
"""

import logging
import time
from typing import Dict, Any, Optional, List, Union, Callable, TYPE_CHECKING

from agent_actions.errors import RateLimitError, NetworkError, VendorAPIError

if TYPE_CHECKING:
    from agent_actions.utilities.retry_tracker import RetryTracker
from agent_actions.llm_invocation.providers.openai.client import OpenAIClient
from agent_actions.llm_invocation.providers.ollama.client import OllamaClient
from agent_actions.llm_invocation.providers.gemini.client import GeminiClient
from agent_actions.llm_invocation.providers.cohere.client import CohereClient
from agent_actions.llm_invocation.providers.mistral.client import MistralClient
from agent_actions.llm_invocation.providers.anthropic.client import AnthropicClient
from agent_actions.llm_invocation.providers.groq.client import GroqClient
from agent_actions.llm_invocation.providers.tools.client import ToolClient

logger = logging.getLogger(__name__)

# Client registry
CLIENT_REGISTRY: Dict[str, Any] = {
    "openai": OpenAIClient,
    "ollama": OllamaClient,
    "gemini": GeminiClient,
    "cohere": CohereClient,
    "mistral": MistralClient,
    "anthropic": AnthropicClient,
    "groq": GroqClient,
    "tool": ToolClient,
}

# Clients that return single response (need wrapping in list)
SINGLE_RESPONSE_CLIENTS: set = {"cohere", "mistral", "anthropic", "groq"}

# Errors that should trigger retry (transient errors)
RETRYABLE_ERRORS = (RateLimitError, NetworkError)

# Default retry settings
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 60.0  # seconds
DEFAULT_BACKOFF_FACTOR = 2.0


class ClientInvocationService:
    """Handles client routing and invocation for agents."""

    @staticmethod
    def _get_retry_config(agent_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract retry configuration from agent config.

        Supports:
            retry: true                    # Use defaults
            retry: false                   # Disable retry
            retry:
              max_retries: 5
              initial_delay: 2.0
              max_delay: 120.0
              backoff_factor: 2.0
        """
        retry_config = agent_config.get("retry", True)

        if retry_config is False:
            return {"enabled": False}

        if retry_config is True:
            return {
                "enabled": True,
                "max_retries": DEFAULT_MAX_RETRIES,
                "initial_delay": DEFAULT_INITIAL_DELAY,
                "max_delay": DEFAULT_MAX_DELAY,
                "backoff_factor": DEFAULT_BACKOFF_FACTOR,
            }

        if isinstance(retry_config, dict):
            return {
                "enabled": retry_config.get("enabled", True),
                "max_retries": retry_config.get("max_retries", DEFAULT_MAX_RETRIES),
                "initial_delay": retry_config.get("initial_delay", DEFAULT_INITIAL_DELAY),
                "max_delay": retry_config.get("max_delay", DEFAULT_MAX_DELAY),
                "backoff_factor": retry_config.get("backoff_factor", DEFAULT_BACKOFF_FACTOR),
            }

        return {"enabled": True, "max_retries": DEFAULT_MAX_RETRIES}

    @staticmethod
    def _invoke_with_retry(
        invoke_fn: Callable[[], List[Any]],
        retry_config: Dict[str, Any],
        model_vendor: str,
        action_name: Optional[str] = None,
        record: Optional[Dict[str, Any]] = None,
        retry_tracker: Optional["RetryTracker"] = None,
    ) -> List[Any]:
        """
        Invoke a function with retry for transient errors.

        Uses exponential backoff with jitter for rate limits and network errors.
        Optionally logs retry events to a retry tracker for debugging.

        Args:
            invoke_fn: Function to invoke (should return response data)
            retry_config: Retry configuration dict
            model_vendor: Vendor name for logging
            action_name: Action/agent name for tracking (optional)
            record: Record data being processed for tracking (optional)
            retry_tracker: RetryTracker instance for persistent logging (optional)

        Returns:
            Response data from successful invocation

        Raises:
            Last exception if all retries exhausted
        """
        if not retry_config.get("enabled", True):
            return invoke_fn()

        max_retries = retry_config.get("max_retries", DEFAULT_MAX_RETRIES)
        initial_delay = retry_config.get("initial_delay", DEFAULT_INITIAL_DELAY)
        max_delay = retry_config.get("max_delay", DEFAULT_MAX_DELAY)
        backoff_factor = retry_config.get("backoff_factor", DEFAULT_BACKOFF_FACTOR)

        last_exception = None
        delay = initial_delay
        entry_id = None

        for attempt in range(max_retries + 1):
            try:
                result = invoke_fn()
                # Mark as success if we had a retry entry
                if entry_id and retry_tracker:
                    retry_tracker.mark_success(entry_id)
                return result
            except RETRYABLE_ERRORS as e:
                last_exception = e

                if attempt >= max_retries:
                    logger.warning(
                        "Max retries (%d) exhausted for %s: %s",
                        max_retries,
                        model_vendor,
                        str(e),
                    )
                    # Mark as exhausted if tracking
                    if entry_id and retry_tracker:
                        retry_tracker.mark_exhausted(entry_id)
                    raise

                # Check for retry_after hint in error context
                retry_after = None
                if hasattr(e, "context") and e.context:
                    retry_after = e.context.get("retry_after")

                wait_time = retry_after if retry_after else delay
                wait_time = min(wait_time, max_delay)

                logger.info(
                    "Retry %d/%d for %s after %.1fs: %s",
                    attempt + 1,
                    max_retries,
                    model_vendor,
                    wait_time,
                    str(e),
                )

                # Log retry event to tracker
                if retry_tracker and action_name:
                    entry_id = retry_tracker.log_retry(
                        action=action_name,
                        mode="online",
                        attempt=attempt + 1,
                        max_attempts=max_retries,
                        error_type=type(e).__name__,
                        error_message=str(e),
                        record=record or {},
                    )

                time.sleep(wait_time)
                delay = min(delay * backoff_factor, max_delay)

        # Should not reach here, but just in case
        if last_exception:
            raise last_exception
        return []

    @staticmethod
    def invoke_client(
        model_vendor: str,
        agent_config: Dict[str, Any],
        prompt_config: str,
        context_data: Union[str, Dict],
        schema: Optional[Dict[str, Any]],
        granularity: str,
        formatted_prompt: Optional[str] = None,
        tool_args: Optional[Dict[str, Any]] = None,
        source_content: Optional[Any] = None,
        output_directory: Optional[str] = None,
        action_name: Optional[str] = None,
    ) -> List[Any]:
        """
        Delegate to the specific client and normalize the response.

        Handles client-specific invocation patterns:
        - Groq: Uses formatted_prompt parameter
        - Tool: Uses tool_args and source_content, early return for file granularity
        - Others: Standard prompt_config and context_data

        Args:
            model_vendor: Client identifier (e.g., 'openai', 'anthropic')
            agent_config: Agent configuration
            prompt_config: Prepared prompt string
            context_data: Context data (str or dict)
            schema: Prepared schema (optional)
            granularity: Processing granularity ('record' or 'file')
            formatted_prompt: Pre-formatted prompt for groq (optional)
            tool_args: Tool arguments (optional)
            source_content: Source content for tool client (optional)
            output_directory: Output directory for retry tracking (optional)
            action_name: Action name for retry tracking (optional)

        Returns:
            List of response items from the client

        Raises:
            ValueError: If client is not supported
        """
        if model_vendor not in CLIENT_REGISTRY:
            raise ValueError(f"Unsupported model vendor: {model_vendor}")

        client = CLIENT_REGISTRY[model_vendor]
        retry_config = ClientInvocationService._get_retry_config(agent_config)

        # Tool client has different parameters and no retry (local execution)
        if model_vendor == "tool":
            response_data = client.invoke(
                agent_config, context_data, tool_args=tool_args, source_content=source_content
            )
            # Tool client with file granularity returns immediately
            if granularity == "file":
                return response_data
            return response_data

        # Define invoke function for retry wrapper
        def do_invoke() -> List[Any]:
            # Groq client has special invocation signature
            if model_vendor == "groq":
                return client.invoke(agent_config, formatted_prompt, context_data, schema)
            # Standard client invocation
            return client.invoke(agent_config, prompt_config, context_data, schema)

        # Get retry tracker - either from explicit output_directory or current context
        retry_tracker = None
        if output_directory:
            from agent_actions.utilities.retry_tracker import get_retry_tracker

            retry_tracker = get_retry_tracker(output_directory)
        else:
            # Check for current tracker context (set by workflow orchestration)
            from agent_actions.utilities.retry_tracker import get_current_retry_tracker

            retry_tracker = get_current_retry_tracker()

        # Prepare record data for tracking
        record = None
        if isinstance(context_data, dict):
            record = context_data
        elif isinstance(context_data, str):
            try:
                import json

                record = json.loads(context_data)
            except (json.JSONDecodeError, TypeError):
                record = {
                    "raw_context": context_data[:500] if len(context_data) > 500 else context_data
                }

        # Invoke with retry for transient errors
        response_data = ClientInvocationService._invoke_with_retry(
            do_invoke,
            retry_config,
            model_vendor,
            action_name=action_name or agent_config.get("agent_type"),
            record=record,
            retry_tracker=retry_tracker,
        )

        # Single-response clients return single item, wrap in list for consistency
        if model_vendor in SINGLE_RESPONSE_CLIENTS:
            return [response_data]

        return response_data
