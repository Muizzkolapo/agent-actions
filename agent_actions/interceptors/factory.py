from __future__ import annotations

"""Factory for creating response interceptors from configuration."""

from typing import Dict, List, Type

from .base import InterceptorChain, ResponseInterceptor
from .reprompt_interceptor import RepromptInterceptor
from .validation_interceptor import ValidationInterceptor


class InterceptorFactory:
    """Factory for creating interceptors from configuration."""

    _interceptor_types: Dict[str, Type[ResponseInterceptor]] = {
        "validation": ValidationInterceptor,
        "reprompt": RepromptInterceptor,
    }

    @classmethod
    def create_interceptor(cls, config: Dict) -> ResponseInterceptor:
        interceptor_type = config.get("type")
        if interceptor_type not in cls._interceptor_types:
            raise ValueError(f"Unknown interceptor type: {interceptor_type}")

        interceptor_class = cls._interceptor_types[interceptor_type]
        interceptor = interceptor_class()
        # Pass the entire config except 'type'
        config_copy = config.copy()
        config_copy.pop("type", None)
        interceptor.configure(config_copy)
        return interceptor

    @classmethod
    def build_chain(cls, configs: List[Dict]) -> InterceptorChain:
        interceptors = [cls.create_interceptor(cfg) for cfg in configs]
        return InterceptorChain(interceptors)

    @classmethod
    def register_interceptor(
        cls, name: str, interceptor_class: Type[ResponseInterceptor]
    ) -> None:
        cls._interceptor_types[name] = interceptor_class
