"""Reprompt interceptor that integrates with the response interceptor system.

This interceptor uses RepromptEngine to:
1. Attempt JSON repair on responses
2. Validate against constraints
3. Generate improved prompts for retry when validation fails
"""

from typing import Any, Dict, List, Optional

from agent_actions.response_processing.base import InterceptorResult, ResponseInterceptor
from agent_actions.reprompting.config import RepromptConfig
from agent_actions.reprompting.engine import RepromptEngine


class RepromptInterceptor(ResponseInterceptor):
    """Interceptor that handles reprompting using the new RepromptEngine.

    Configured from action-level 'reprompt' and 'constraints' fields.

    Usage in YAML:
        actions:
          - name: my_action
            reprompt: true  # or 'smart' or 'thorough'
            constraints:
              - not_contains: maze
              - required_fields: [name, description]
    """

    def __init__(self) -> None:
        """Initialize without configuration - configure() must be called."""
        self.engine: Optional[RepromptEngine] = None
        self.config: Optional[RepromptConfig] = None
        self.prompt_debug: bool = False

    def configure(self, config: Dict[str, Any]) -> None:
        """Configure the interceptor from action config.

        Args:
            config: Configuration dict with:
                - reprompt: bool, str, or dict (see RepromptConfig.from_yaml)
                - constraints: List of constraint configurations
                - prompt_debug: Whether to print debug info
        """
        self.prompt_debug = config.get("prompt_debug", False)

        if self.prompt_debug:
            print("🔄 REPROMPT INTERCEPTOR CONFIGURE:")
            print(f"   Config received: {config}")

        # Parse reprompt config
        reprompt_value = config.get("reprompt", True)
        self.config = RepromptConfig.from_yaml(reprompt_value)

        if self.prompt_debug:
            print(f"   Parsed config: enabled={self.config.enabled}, "
                  f"preset={self.config.preset}, "
                  f"max_attempts={self.config.max_attempts}")

        # Get constraints from config
        constraints: List[Dict[str, Any]] = config.get("constraints", [])

        # Merge with any constraints from reprompt config
        if self.config.constraints:
            constraints = constraints + self.config.constraints

        if self.prompt_debug:
            print(f"   Constraints: {constraints}")

        # Create engine
        self.engine = RepromptEngine(self.config, constraints)

        if self.prompt_debug:
            print("   Engine created successfully")

    def intercept(self, response: Any, context: Dict[str, Any]) -> InterceptorResult:
        """Process response through reprompt engine.

        Args:
            response: The LLM response to process
            context: Context dict with:
                - original_prompt: The original prompt
                - prompt: Current prompt (may differ after retry)
                - attempt: Current attempt number
                - json_mode: Whether JSON output is expected
                - validation_error: Error from previous validation (if any)

        Returns:
            InterceptorResult with:
                - continue_processing=True if response is valid
                - retry_context with improved_prompt if retry needed
        """
        if self.prompt_debug:
            print("🧠 REPROMPT INTERCEPTOR INTERCEPT:")
            print(f"   Context keys: {list(context.keys())}")

        # If not configured or disabled, continue processing
        if not self.engine or not self.config or not self.config.enabled:
            if self.prompt_debug:
                print("   Engine not configured or disabled - continuing")
            return InterceptorResult(continue_processing=True)

        # Get attempt from context
        attempt = context.get("attempt", 0)

        if self.prompt_debug:
            print(f"   Current attempt: {attempt}, Max attempts: {self.config.max_attempts}")

        # Check if we've exceeded max attempts
        if attempt >= self.config.max_attempts:
            if self.prompt_debug:
                print("   MAX ATTEMPTS REACHED - stopping")
            return InterceptorResult(
                continue_processing=False,
                metadata={"max_attempts_reached": True},
            )

        # Process through engine
        result = self.engine.process_response(response, context)

        if self.prompt_debug:
            print(f"   Engine result: success={result.success}, "
                  f"needs_retry={result.needs_retry}")
            if result.error:
                print(f"   Error: {result.error}")
            if result.repair_method:
                print(f"   Repair method: {result.repair_method}")

        # If successful, return modified response (possibly repaired)
        if result.success:
            if self.prompt_debug:
                print("   ✅ Validation passed")
            return InterceptorResult(
                continue_processing=True,
                modified_response=result.response,
                metadata={
                    "repair_method": result.repair_method,
                    "attempt": result.attempt,
                },
            )

        # If retry needed, return retry context
        if result.needs_retry:
            if self.prompt_debug:
                print("   🔄 Retry needed with improved prompt")

            # Get history from context
            history = context.get("history", []) + [
                {
                    "attempt": attempt,
                    "prompt": context.get("prompt"),
                    "error": result.error,
                }
            ]

            return InterceptorResult(
                continue_processing=False,
                retry_context={
                    "prompt": result.improved_prompt,
                    "original_prompt": context.get(
                        "original_prompt", context.get("prompt")
                    ),
                    "attempt": result.attempt,
                    "history": history,
                    "validation_error": result.error,
                    "failed_response": response,
                },
                metadata={
                    "repair_method": result.repair_method,
                    "constraint_failed": result.constraint_failed,
                },
            )

        # Max attempts reached in engine
        if result.metadata.get("max_attempts_reached"):
            if self.prompt_debug:
                print("   MAX ATTEMPTS REACHED in engine - stopping")
            return InterceptorResult(
                continue_processing=False,
                modified_response=result.response,
                metadata={"max_attempts_reached": True},
            )

        # Fallback - continue processing
        return InterceptorResult(
            continue_processing=True,
            modified_response=result.response,
        )
