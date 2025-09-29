from __future__ import annotations

"""Interceptor that validates responses using user-defined functions.

User-defined validators must:
1. Accept (response: Any, **kwargs) where response is the raw API response
2. Extract content from the response structure as needed
3. Return Tuple[bool, str | None] - (success, error_message)
"""

from typing import Any, Dict

from agent_actions.integrations.interceptors.base import InterceptorResult, ResponseInterceptor
from agent_actions.core.tooling import load_user_defined_function, _split_udf_name
from agent_actions.core.context import context as artifact_context
from agent_actions.core.contracts.base import SecurityError
from agent_actions.cli.exceptions import AgentActionsError, ConfigurationError


class ValidationInterceptor(ResponseInterceptor):
    """Interceptor that validates responses against configured criteria."""

    def __init__(self) -> None:
        self.validator_function: str | None = None
        self.validator_args: Dict[str, Any] = {}
        self.on_failure: str = "retry"
        self.prompt_debug: bool = False

    def configure(self, config: Dict) -> None:
        self.prompt_debug = config.get("prompt_debug", False)

        if self.prompt_debug:
            print(f"🔧 VALIDATION INTERCEPTOR CONFIGURE:")
            print(f"   Config received: {config}")

        self.validator_function = config.get("validator_function")
        self.validator_args = config.get("validator_args", {})
        self.on_failure = config.get("on_failure", "retry")

        if self.prompt_debug:
            print(f"   Parsed validator_function: {self.validator_function}")
            print(f"   Parsed validator_args: {self.validator_args}")
            print(f"   Parsed on_failure: {self.on_failure}")

        if not self.validator_function:
            raise ValueError("validator_function is required")

    def intercept(self, response: Any, context: Dict) -> InterceptorResult:
        if self.prompt_debug:
            print(f"🔍 VALIDATION INTERCEPTOR INTERCEPT:")
            print(f"   Response type: {type(response)}")
            print(f"   Context attempt: {context.get('attempt', 'unknown')}")
            print(f"   Raw response: {response}")

        if not self.validator_function:
            if self.prompt_debug:
                print(f"   ⚠️ No validator function - continuing")
            return InterceptorResult(continue_processing=True)

        if self.prompt_debug:
            print(f"   🔍 Running validator function '{self.validator_function}' with args: {self.validator_args}")

        try:
            # Load and call the user-defined validator function
            # The validator function must:
            # 1. Accept (response: Any, **kwargs) where response is the raw API response
            # 2. Extract content from the response structure (e.g., response["poem"] for poem field)
            # 3. Return Tuple[bool, str | None] - (success, error_message)
            module_name, func_name = _split_udf_name(self.validator_function)
            validator_func = load_user_defined_function(module_name, func_name)

            # Merge validator args with context data so validator can access target_word_counts
            merged_kwargs = {**self.validator_args, **context}
            success, error_message = validator_func(response, **merged_kwargs)
        except (ConfigurationError, AgentActionsError) as e:
            if self.prompt_debug:
                print(f"   ❌ Error loading/executing validator function: {e}")
            # Treat as validation failure
            success, error_message = False, f"Validator function error: {str(e)}"

        if self.prompt_debug:
            print(f"   📊 VALIDATION RESULT: success={success}")
            if error_message:
                print(f"      Error: {error_message}")

        # ARTIFACT SYSTEM INTEGRATION: Record validation attempt
        self._record_validation_attempt(context, success, error_message, str(response)[:500])

        if success:
            if self.prompt_debug:
                print(f"   ✅ VALIDATION PASSED - continuing with response")
            return InterceptorResult(continue_processing=True)

        if self.on_failure == "retry":
            if self.prompt_debug:
                print(f"   ❌ VALIDATION FAILED - setting up retry with reprompt interceptor")
                print(f"      Will trigger reprompt to generate improved prompt")
            return InterceptorResult(
                continue_processing=False,
                retry_context={
                    "validation_error": error_message,
                    "validator_function": self.validator_function,
                    "validator_args": self.validator_args,
                    "failed_response": response,
                    # Don't increment attempt here - let reprompt interceptor handle it
                },
            )
        if self.on_failure == "fail":
            if self.prompt_debug:
                print(f"   ❌ VALIDATION FAILED - raising error")
            raise ValueError(f"Validation failed: {error_message}")

        if self.prompt_debug:
            print(f"   ⚠️ VALIDATION FAILED - continuing with warning")
        return InterceptorResult(
            continue_processing=True,
            metadata={"validation_warning": error_message},
        )
    
    def _record_validation_attempt(
        self, 
        context: Dict, 
        success: bool, 
        error_message: str | None, 
        response_content: str
    ) -> None:
        """Record validation attempt in artifact system if available."""
        artifact_manager = artifact_context.get_artifact_manager()
        if not artifact_manager:
            return
        
        try:
            # Try to extract agent name from context or use a default
            agent_name = context.get("agent_name", "unknown_agent")
            if not agent_name or agent_name == "unknown_agent":
                # Try to get from agent_config if available
                agent_config = context.get("agent_config", {})
                agent_name = agent_config.get("agent_type", "unknown_agent")
            
            attempt = context.get("attempt", 1) + 1  # attempt is 0-based, make it 1-based
            status = "success" if success else "error"
            
            artifact_manager.record_validation_attempt(
                agent_id=agent_name,
                validator_type=self.validator_function or "unknown_validator",
                attempt=attempt,
                status=status,
                error=error_message if not success else None,
                response=response_content[:500] if response_content else None  # Truncate for storage
            )
            
            if self.prompt_debug:
                print(f"   📊 Recorded validation attempt: {agent_name} -> {self.validator_function} -> {status}")
                
        except SecurityError as e:
            if self.prompt_debug:
                print(f"   ⚠️ Could not record validation attempt: {e}")
        except Exception as e:
            if self.prompt_debug:
                print(f"   ⚠️ Error recording validation attempt: {e}")

