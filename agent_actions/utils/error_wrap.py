"""Decorator for wrapping exceptions as validation errors."""

from functools import wraps
from typing import Callable, Type

from agent_actions.errors import ConfigurationError


def as_validation_error(exc_cls: Type[ConfigurationError] = ConfigurationError) -> Callable:
    """
    Any exception inside the wrapped function is re-raised as `exc_cls`
    **from None**, so Python prints zero traceback / file paths.
    """

    def _decorator(fn: Callable):
        @wraps(fn)
        def _wrapper(*a, **k):
            try:
                return fn(*a, **k)
            except Exception as exc:
                raise exc_cls(str(exc)) from None

        return _wrapper

    return _decorator
