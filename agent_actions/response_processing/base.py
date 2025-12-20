"""Base classes and utilities for response interceptors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class InterceptorResult:
    """Result from an interceptor's processing."""

    continue_processing: bool = True
    modified_response: Optional[Any] = None
    retry_context: Optional[Dict] = None
    metadata: Dict | None = None


class ResponseInterceptor(ABC):
    """Base class for all response interceptors."""

    @abstractmethod
    def intercept(self, response: Any, context: Dict) -> InterceptorResult:
        """Process the response and determine next action."""

    @abstractmethod
    def configure(self, config: Dict) -> None:
        """Configure the interceptor from agent config."""


# pylint: disable=too-few-public-methods
class InterceptorChain:
    """Manages the chain of interceptors."""

    def __init__(self, interceptors: List[ResponseInterceptor]):
        self.interceptors = interceptors

    def process(self, response: Any, context: Dict) -> InterceptorResult:
        """Run response through all interceptors."""

        current_response = response
        for interceptor in self.interceptors:
            result = interceptor.intercept(current_response, context)

            if result.modified_response is not None:
                current_response = result.modified_response

            if result.retry_context:
                return result

            if not result.continue_processing:
                return InterceptorResult(
                    continue_processing=False,
                    modified_response=current_response,
                    metadata=result.metadata,
                )

        return InterceptorResult(
            continue_processing=True, modified_response=current_response
        )
