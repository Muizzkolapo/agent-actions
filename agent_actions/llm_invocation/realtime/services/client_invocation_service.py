"""Client invocation service for agent builder.

Handles client routing, invocation, and recovery for transient errors.
Uses unified RecoveryConfig for consistent retry handling across all providers.
Supports retry event tracking for debugging and analysis.
"""

import json
import logging
import time
import random
from typing import Dict, Any, Optional, List, Union, Callable, TYPE_CHECKING

from agent_actions.errors import RateLimitError, NetworkError
from agent_actions.recovery.recovery_config import RecoveryConfig, ExhaustedBehavior

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


class ClientInvocationService:
    """Handles client routing and invocation for agents.

    Uses unified RecoveryConfig for retry configuration, supporting:
    - retry: true | false | strict | {detailed config}
    - Exponential backoff with jitter
    - Configurable exhaustion behavior (continue, fail, dead_letter)
    - Event tracking via RetryTracker
    """

    @staticmethod
    def _get_recovery_config(agent_config: Dict[str, Any]) -> RecoveryConfig:
        """
        Extract recovery configuration from agent config.

        Supports both legacy and new formats:
            # Legacy formats
            retry: true
            retry: false
            retry: strict
            retry:
              max_attempts: 5
              on_exhausted: dead_letter

            # New unified format
            recovery:
              retry:
                max_attempts: 3
                on_exhausted: fail
              reprompt:
                preset: smart
        """
        # Check for new unified recovery config
        recovery_value = agent_config.get("recovery")
        if recovery_value is not None:
            return RecoveryConfig.from_yaml(recovery_value=recovery_value)

        # Fall back to legacy retry config
        retry_value = agent_config.get("retry", True)
        reprompt_value = agent_config.get("reprompt", False)
        return RecoveryConfig.from_yaml(retry_value=retry_value, reprompt_value=reprompt_value)

    @staticmethod
    def _calculate_backoff(
        attempt: int,
        base_delay: float,
        max_delay: float,
        error: Optional[Exception] = None,
    ) -> float:
        """Calculate exponential backoff with jitter.

        Args:
            attempt: Current attempt number (1-indexed)
            base_delay: Base delay in seconds
            max_delay: Maximum delay in seconds
            error: The error (may contain retry_after header)

        Returns:
            Delay in seconds
        """
        # Check for retry_after header from provider
        if error and hasattr(error, "context") and error.context:
            retry_after = error.context.get("retry_after")
            if retry_after:
                return min(float(retry_after), max_delay)

        # Exponential backoff: base * 2^(attempt-1)
        delay = base_delay * (2 ** (attempt - 1))

        # Add jitter (0-25%) to avoid thundering herd
        jitter = delay * random.uniform(0, 0.25)
        delay += jitter

        return min(delay, max_delay)

    @staticmethod
    def _invoke_with_retry(
        invoke_fn: Callable[[], List[Any]],
        recovery_config: RecoveryConfig,
        model_vendor: str,
        action_name: Optional[str] = None,
        record: Optional[Dict[str, Any]] = None,
        retry_tracker: Optional["RetryTracker"] = None,
    ) -> List[Any]:
        """
        Invoke a function with retry for transient errors.

        Uses exponential backoff with jitter for rate limits and network errors.
        Handles exhaustion based on recovery_config.retry.on_exhausted.

        Args:
            invoke_fn: Function to invoke (should return response data)
            recovery_config: RecoveryConfig with retry settings
            model_vendor: Vendor name for logging
            action_name: Action/agent name for tracking (optional)
            record: Record data being processed for tracking (optional)
            retry_tracker: RetryTracker instance for persistent logging (optional)

        Returns:
            Response data from successful invocation

        Raises:
            Last exception if all retries exhausted and on_exhausted=fail
            ProcessingError if on_exhausted=fail
        """
        retry_config = recovery_config.retry

        if not retry_config.enabled:
            return invoke_fn()

        max_attempts = retry_config.max_attempts
        base_delay = retry_config.backoff_base
        max_delay = retry_config.backoff_max

        last_exception = None
        entry_id = None

        for attempt in range(1, max_attempts + 1):
            try:
                result = invoke_fn()
                # Mark as success if we had a retry entry
                if entry_id and retry_tracker:
                    retry_tracker.mark_success(entry_id)
                return result

            except RETRYABLE_ERRORS as e:
                last_exception = e

                # Log retry event to tracker
                if retry_tracker and action_name:
                    entry_id = retry_tracker.log_retry(
                        action=action_name,
                        mode="online",
                        attempt=attempt,
                        max_attempts=max_attempts,
                        error_type=type(e).__name__,
                        error_message=str(e),
                        record=record or {},
                    )

                if attempt >= max_attempts:
                    # Mark as exhausted
                    if entry_id and retry_tracker:
                        retry_tracker.mark_exhausted(entry_id)

                    logger.warning(
                        "Retry exhausted for %s after %d attempts: %s",
                        model_vendor,
                        max_attempts,
                        str(e),
                    )

                    # Handle based on on_exhausted behavior
                    return ClientInvocationService._handle_exhausted(
                        retry_config.on_exhausted,
                        e,
                        action_name or model_vendor,
                        max_attempts,
                    )

                # Calculate backoff delay
                wait_time = ClientInvocationService._calculate_backoff(
                    attempt, base_delay, max_delay, e
                )

                logger.info(
                    "Retry %d/%d for %s after %.1fs: %s",
                    attempt,
                    max_attempts,
                    model_vendor,
                    wait_time,
                    str(e),
                )

                time.sleep(wait_time)

        # Should not reach here, but just in case
        if last_exception:
            raise last_exception
        return []

    @staticmethod
    def _handle_exhausted(
        behavior: ExhaustedBehavior,
        error: Exception,
        action_name: str,
        attempts: int,
    ) -> List[Any]:
        """Handle exhausted retry attempts based on configured behavior.

        Args:
            behavior: ExhaustedBehavior (continue, fail, dead_letter)
            error: The last exception
            action_name: Name of the action that failed
            attempts: Number of attempts made

        Returns:
            Empty list for continue/dead_letter

        Raises:
            ProcessingError for fail behavior
        """
        if behavior == ExhaustedBehavior.FAIL:
            from agent_actions.errors import ProcessingError

            raise ProcessingError(
                f"Retry exhausted for '{action_name}' after {attempts} attempts: {error}",
                context={
                    "action": action_name,
                    "attempts": attempts,
                    "last_error": str(error),
                    "on_exhausted": "fail",
                },
            )

        # CONTINUE or DEAD_LETTER - return empty, let caller handle
        # Dead letter handling happens at a higher level (workflow orchestration)
        if behavior == ExhaustedBehavior.DEAD_LETTER:
            logger.info(
                "Record will be written to dead letter for '%s' after %d attempts",
                action_name,
                attempts,
            )

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
        recovery_config = ClientInvocationService._get_recovery_config(agent_config)

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
                record = json.loads(context_data)
            except (json.JSONDecodeError, TypeError):
                record = {
                    "raw_context": context_data[:500] if len(context_data) > 500 else context_data
                }

        # Invoke with retry for transient errors
        response_data = ClientInvocationService._invoke_with_retry(
            do_invoke,
            recovery_config,
            model_vendor,
            action_name=action_name or agent_config.get("agent_type"),
            record=record,
            retry_tracker=retry_tracker,
        )

        # Single-response clients return single item, wrap in list for consistency
        if model_vendor in SINGLE_RESPONSE_CLIENTS:
            return [response_data]

        return response_data
