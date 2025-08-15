from __future__ import annotations

"""Interceptor that validates responses against configured criteria."""

from typing import Any, Dict

from .base import InterceptorResult, ResponseInterceptor
from ..validators.registry import ValidatorRegistry
from ..artifacts import context as artifact_context
from ..artifacts.base import SecurityError


class ValidationInterceptor(ResponseInterceptor):
    """Interceptor that validates responses against configured criteria."""

    def __init__(self) -> None:
        self.validator_name: str | None = None
        self.validator_args: Dict[str, Any] = {}
        self.on_failure: str = "retry"
        self.validator_func = None
        self.prompt_debug: bool = False

    def configure(self, config: Dict) -> None:
        self.prompt_debug = config.get("prompt_debug", False)
        
        if self.prompt_debug:
            print(f"🔧 VALIDATION INTERCEPTOR CONFIGURE:")
            print(f"   Config received: {config}")
            print(f"   Available validators: {ValidatorRegistry.list_validators()}")
        
        self.validator_name = config.get("validator")
        self.validator_args = config.get("validator_args", {})
        self.on_failure = config.get("on_failure", "retry")

        if self.prompt_debug:
            print(f"   Parsed validator_name: {self.validator_name}")
            print(f"   Parsed validator_args: {self.validator_args}")
            print(f"   Parsed on_failure: {self.on_failure}")

        self.validator_func = ValidatorRegistry.get(self.validator_name)
        if self.prompt_debug:
            print(f"   Retrieved validator_func: {self.validator_func}")
        
        if not self.validator_func:
            raise ValueError(f"Unknown validator: {self.validator_name}")

    def intercept(self, response: Any, context: Dict) -> InterceptorResult:
        if self.prompt_debug:
            print(f"🔍 VALIDATION INTERCEPTOR INTERCEPT:")
            print(f"   Response type: {type(response)}")
            print(f"   Context attempt: {context.get('attempt', 'unknown')}")
        
        if not self.validator_func:
            if self.prompt_debug:
                print(f"   ⚠️ No validator function - continuing")
            return InterceptorResult(continue_processing=True)

        content = self._extract_content(response)
        if self.prompt_debug:
            print(f"   Raw response: {response}")
            print(f"   Extracted content: '{content[:100]}...' (first 100 chars)")
            print(f"   Full content: '{content}'")
            print(f"   Running validator '{self.validator_name}' with args: {self.validator_args}")
        
        success, error_message = self.validator_func(content, **self.validator_args)
        if self.prompt_debug:
            print(f"   Validation result: success={success}, error='{error_message}'")
        
        # ARTIFACT SYSTEM INTEGRATION: Record validation attempt
        self._record_validation_attempt(context, success, error_message, content)

        if success:
            if self.prompt_debug:
                print(f"   ✅ VALIDATION PASSED - continuing")
            return InterceptorResult(continue_processing=True)

        if self.on_failure == "retry":
            if self.prompt_debug:
                print(f"   ❌ VALIDATION FAILED - setting up retry")
            return InterceptorResult(
                continue_processing=False,
                retry_context={
                    "validation_error": error_message,
                    "validator_name": self.validator_name,
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
                validator_type=self.validator_name or "unknown_validator",
                attempt=attempt,
                status=status,
                error=error_message if not success else None,
                response=response_content[:500] if response_content else None  # Truncate for storage
            )
            
            if self.prompt_debug:
                print(f"   📊 Recorded validation attempt: {agent_name} -> {self.validator_name} -> {status}")
                
        except SecurityError as e:
            if self.prompt_debug:
                print(f"   ⚠️ Could not record validation attempt: {e}")
        except Exception as e:
            if self.prompt_debug:
                print(f"   ⚠️ Error recording validation attempt: {e}")

    def _extract_content(self, response: Any) -> str:
        if isinstance(response, list) and response:
            first_item = response[0]
            if isinstance(first_item, dict):
                # Try multiple keys: content, text, summary, and all values
                content = (first_item.get("content", "") or 
                          first_item.get("text", "") or 
                          first_item.get("summary", "") or
                          " ".join(str(v) for v in first_item.values() if v))
                return content
            return str(first_item)
        if isinstance(response, dict):
            # Try multiple keys: content, text, summary, and all values  
            content = (response.get("content", "") or 
                      response.get("text", "") or 
                      response.get("summary", "") or
                      " ".join(str(v) for v in response.values() if v))
            return content
        return str(response)
