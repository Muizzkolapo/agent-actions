from __future__ import annotations

"""Interceptor that validates responses against configured criteria."""

from typing import Any, Dict

from .base import InterceptorResult, ResponseInterceptor
from ..validators.registry import ValidatorRegistry


class ValidationInterceptor(ResponseInterceptor):
    """Interceptor that validates responses against configured criteria."""

    def __init__(self) -> None:
        self.validator_name: str | None = None
        self.validator_args: Dict[str, Any] = {}
        self.on_failure: str = "retry"
        self.validator_func = None

    def configure(self, config: Dict) -> None:
        print(f"🔧 VALIDATION INTERCEPTOR CONFIGURE:")
        print(f"   Config received: {config}")
        print(f"   Available validators: {ValidatorRegistry.list_validators()}")
        
        self.validator_name = config.get("validator")
        self.validator_args = config.get("validator_args", {})
        self.on_failure = config.get("on_failure", "retry")

        print(f"   Parsed validator_name: {self.validator_name}")
        print(f"   Parsed validator_args: {self.validator_args}")
        print(f"   Parsed on_failure: {self.on_failure}")

        self.validator_func = ValidatorRegistry.get(self.validator_name)
        print(f"   Retrieved validator_func: {self.validator_func}")
        
        if not self.validator_func:
            raise ValueError(f"Unknown validator: {self.validator_name}")

    def intercept(self, response: Any, context: Dict) -> InterceptorResult:
        print(f"🔍 VALIDATION INTERCEPTOR INTERCEPT:")
        print(f"   Response type: {type(response)}")
        print(f"   Context attempt: {context.get('attempt', 'unknown')}")
        
        if not self.validator_func:
            print(f"   ⚠️ No validator function - continuing")
            return InterceptorResult(continue_processing=True)

        content = self._extract_content(response)
        print(f"   Raw response: {response}")
        print(f"   Extracted content: '{content[:100]}...' (first 100 chars)")
        print(f"   Full content: '{content}'")
        print(f"   Running validator '{self.validator_name}' with args: {self.validator_args}")
        
        success, error_message = self.validator_func(content, **self.validator_args)
        print(f"   Validation result: success={success}, error='{error_message}'")

        if success:
            print(f"   ✅ VALIDATION PASSED - continuing")
            return InterceptorResult(continue_processing=True)

        if self.on_failure == "retry":
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
            print(f"   ❌ VALIDATION FAILED - raising error")
            raise ValueError(f"Validation failed: {error_message}")

        print(f"   ⚠️ VALIDATION FAILED - continuing with warning")
        return InterceptorResult(
            continue_processing=True,
            metadata={"validation_warning": error_message},
        )

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
