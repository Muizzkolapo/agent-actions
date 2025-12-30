"""Factory for creating response interceptors from configuration."""

from __future__ import annotations
from typing import Dict, List, Type

from agent_actions.errors import ConfigurationError
from agent_actions.reprompting.interceptor import RepromptInterceptor
from agent_actions.validation.validation_interceptor import ValidationInterceptor

from .base import InterceptorChain, ResponseInterceptor


class InterceptorFactory:
    """Factory for creating interceptors from configuration."""

    _interceptor_types: Dict[str, Type[ResponseInterceptor]] = {
        "validation": ValidationInterceptor,
        "reprompt": RepromptInterceptor,
    }

    @classmethod
    def create_interceptor(cls, config: Dict) -> ResponseInterceptor:
        """Create an interceptor instance from configuration."""
        interceptor_type = config.get("type")
        if interceptor_type not in cls._interceptor_types:
            supported = list(cls._interceptor_types.keys())
            raise ConfigurationError(
                "Unknown interceptor type",
                context={
                    "interceptor_type": interceptor_type,
                    "supported_types": supported,
                    "suggestion": (
                        f"Use one of: {', '.join(supported)}. Check your interceptor configuration."
                    ),
                },
            )
        interceptor_class = cls._interceptor_types[interceptor_type]
        interceptor = interceptor_class()
        config_copy = config.copy()
        config_copy.pop("type", None)
        interceptor.configure(config_copy)
        return interceptor

    @classmethod
    def build_chain(cls, configs: List[Dict]) -> InterceptorChain:
        """Build an interceptor chain from a list of configurations."""
        interceptors = [cls.create_interceptor(cfg) for cfg in configs]
        return InterceptorChain(interceptors)

    @classmethod
    def register_interceptor(cls, name: str, interceptor_class: Type[ResponseInterceptor]) -> None:
        """Register a new interceptor type."""
        cls._interceptor_types[name] = interceptor_class
