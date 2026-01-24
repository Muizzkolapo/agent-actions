"""
Reprompt validation UDF system.

Provides decorator for registering validation functions and
feedback message management.

Thread-safe: All registry access is protected by a lock for concurrent environments.
"""

from typing import Dict, Callable, Tuple
import logging
import threading

from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    DataValidationFailedEvent,
    DataValidationPassedEvent,
    DataValidationStartedEvent,
)

logger = logging.getLogger(__name__)

# Global registry: UDF name -> (function, message)
_VALIDATION_REGISTRY: Dict[str, Tuple[Callable[[dict], bool], str]] = {}

# Lock for thread-safe registry access
_REGISTRY_LOCK = threading.Lock()


def reprompt_validation(feedback_message: str):
    """
    Decorator to register reprompt validation UDFs.

    The decorated function should validate an LLM response and return
    True if valid (pass) or False to trigger reprompt.

    Args:
        feedback_message: Message shown to LLM when validation fails.
                         This explains what needs to be corrected.

    Returns:
        Decorator function

    Example:
        @reprompt_validation("Response must not contain forbidden words")
        def check_no_forbidden_words(response: dict) -> bool:
            forbidden = ["spam", "scam"]
            text = str(response).lower()
            return not any(word in text for word in forbidden)

    Note:
        - Function name becomes the UDF identifier
        - Function must accept dict parameter and return bool
        - Registered functions are stored in global registry
    """

    def decorator(func: Callable[[dict], bool]) -> Callable[[dict], bool]:
        func_name = func.__name__

        # Create wrapper that fires events
        def wrapped_func(response: dict) -> bool:
            # Fire validation started event
            fire_event(
                DataValidationStartedEvent(
                    validator_type=f"RepromptValidation:{func_name}",
                    target="LLM response",
                )
            )

            # Execute validation
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
                fire_event(
                    DataValidationFailedEvent(
                        validator_type=f"RepromptValidation:{func_name}",
                        errors=[str(e)],
                    )
                )
                raise

        # Thread-safe registration
        with _REGISTRY_LOCK:
            _VALIDATION_REGISTRY[func_name] = (wrapped_func, feedback_message)
            logger.debug(f"Registered reprompt validation: {func_name}")
        return wrapped_func

    return decorator


def get_validation_function(name: str) -> Tuple[Callable[[dict], bool], str]:
    """
    Get validation function and feedback message by name.

    Args:
        name: UDF function name (as registered by decorator)

    Returns:
        Tuple of (validation_function, feedback_message)

    Raises:
        ValueError: If UDF not found in registry

    Example:
        validator, message = get_validation_function("check_no_forbidden_words")
        is_valid = validator(response)
    """
    # Thread-safe lookup
    with _REGISTRY_LOCK:
        if name not in _VALIDATION_REGISTRY:
            available = list(_VALIDATION_REGISTRY.keys())
            raise ValueError(f"Validation UDF '{name}' not found. Available: {available}")
        return _VALIDATION_REGISTRY[name]


def list_validation_functions() -> list[str]:
    """
    List all registered validation function names.

    Returns:
        List of UDF names in registry

    Example:
        >>> list_validation_functions()
        ['check_no_forbidden_words', 'check_format', 'check_required_fields']
    """
    # Thread-safe list copy
    with _REGISTRY_LOCK:
        return list(_VALIDATION_REGISTRY.keys())
