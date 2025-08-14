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
        self.validator_name = config.get("validator")
        self.validator_args = config.get("validator_args", {})
        self.on_failure = config.get("on_failure", "retry")

        self.validator_func = ValidatorRegistry.get(self.validator_name)
        if not self.validator_func:
            raise ValueError(f"Unknown validator: {self.validator_name}")

    def intercept(self, response: Any, context: Dict) -> InterceptorResult:
        if not self.validator_func:
            return InterceptorResult(continue_processing=True)

        content = self._extract_content(response)
        success, error_message = self.validator_func(content, **self.validator_args)

        if success:
            return InterceptorResult(continue_processing=True)

        if self.on_failure == "retry":
            return InterceptorResult(
                continue_processing=False,
                retry_context={
                    "validation_error": error_message,
                    "validator_name": self.validator_name,
                    "validator_args": self.validator_args,
                    "failed_response": response,
                },
            )
        if self.on_failure == "fail":
            raise ValueError(f"Validation failed: {error_message}")

        return InterceptorResult(
            continue_processing=True,
            metadata={"validation_warning": error_message},
        )

    def _extract_content(self, response: Any) -> str:
        if isinstance(response, list) and response:
            first_item = response[0]
            if isinstance(first_item, dict):
                return first_item.get("content", "") or first_item.get("text", "")
            return str(first_item)
        if isinstance(response, dict):
            return response.get("content", "") or response.get("text", "")
        return str(response)
