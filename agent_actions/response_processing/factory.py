from __future__ import annotations
'Factory for creating response interceptors from configuration.'
from typing import Dict, List, Type
from .base import InterceptorChain, ResponseInterceptor
from agent_actions.prompt_generation.reprompt_interceptor import RepromptInterceptor
from agent_actions.validation.validation_interceptor import ValidationInterceptor

class InterceptorFactory:
    """Factory for creating interceptors from configuration."""
    _interceptor_types: Dict[str, Type[ResponseInterceptor]] = {'validation': ValidationInterceptor, 'reprompt': RepromptInterceptor}

    @classmethod
    def create_interceptor(cls, config: Dict) -> ResponseInterceptor:
        interceptor_type = config.get('type')
        if interceptor_type not in cls._interceptor_types:
            from agent_actions.shared.exceptions import ConfigurationError
            raise ConfigurationError('Unknown interceptor type', context={'interceptor_type': interceptor_type, 'supported_types': list(cls._interceptor_types.keys())})
        interceptor_class = cls._interceptor_types[interceptor_type]
        interceptor = interceptor_class()
        config_copy = config.copy()
        config_copy.pop('type', None)
        interceptor.configure(config_copy)
        return interceptor

    @classmethod
    def build_chain(cls, configs: List[Dict]) -> InterceptorChain:
        interceptors = [cls.create_interceptor(cfg) for cfg in configs]
        return InterceptorChain(interceptors)

    @classmethod
    def register_interceptor(cls, name: str, interceptor_class: Type[ResponseInterceptor]) -> None:
        cls._interceptor_types[name] = interceptor_class