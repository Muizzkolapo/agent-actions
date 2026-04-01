"""Thread-safe reprompt validation UDF registry."""

import functools
import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

_VALIDATION_REGISTRY: dict[str, tuple[Callable[[dict], bool], str]] = {}
_REGISTRY_LOCK = threading.Lock()


def reprompt_validation(feedback_message: str):
    """Decorator to register a reprompt validation UDF.

    The decorated function receives a dict response and returns True (pass)
    or False (trigger reprompt). The function name becomes the UDF identifier.

    Args:
        feedback_message: Message shown to LLM when validation fails.
    """

    def decorator(func: Callable[[dict], bool]) -> Callable[[dict], bool]:
        func_name = func.__name__

        @functools.wraps(func)
        def wrapped_func(response: dict) -> bool:
            from agent_actions.logging.core.manager import fire_event
            from agent_actions.logging.events import (
                DataValidationFailedEvent,
                DataValidationPassedEvent,
                DataValidationStartedEvent,
            )

            fire_event(
                DataValidationStartedEvent(
                    validator_type=f"RepromptValidation:{func_name}",
                    target="LLM response",
                )
            )

            try:
                result = func(response)
                if result:
                    fire_event(
                        DataValidationPassedEvent(
                            validator_type=f"RepromptValidation:{func_name}",
                            item_count=1,
                        )
                    )
                else:
                    fire_event(
                        DataValidationFailedEvent(
                            validator_type=f"RepromptValidation:{func_name}",
                            errors=[feedback_message],
                        )
                    )
                return result
            except Exception as e:
                try:
                    fire_event(
                        DataValidationFailedEvent(
                            validator_type=f"RepromptValidation:{func_name}",
                            errors=[str(e)],
                        )
                    )
                except Exception:
                    logger.debug(
                        "Failed to fire DataValidationFailedEvent for %s",
                        func_name,
                        exc_info=True,
                    )
                raise

        with _REGISTRY_LOCK:
            if func_name in _VALIDATION_REGISTRY:
                logger.warning("Overwriting existing reprompt validation: %s", func_name)
            _VALIDATION_REGISTRY[func_name] = (wrapped_func, feedback_message)
            logger.debug("Registered reprompt validation: %s", func_name)
        return wrapped_func

    return decorator


def get_validation_function(name: str) -> tuple[Callable[[dict], bool], str]:
    """Return (validation_function, feedback_message) for the named UDF.

    Raises:
        ValueError: If UDF not found in registry.
    """
    with _REGISTRY_LOCK:
        if name not in _VALIDATION_REGISTRY:
            available = list(_VALIDATION_REGISTRY.keys())
            raise ValueError(f"Validation UDF '{name}' not found. Available: {available}")
        return _VALIDATION_REGISTRY[name]


def list_validation_functions() -> list[str]:
    """Return all registered validation function names."""
    with _REGISTRY_LOCK:
        return list(_VALIDATION_REGISTRY.keys())
