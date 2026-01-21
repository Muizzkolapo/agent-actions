"""
Compatibility module for reprompt validation decorators.

Legacy code and documentation expect `agent_actions.processing.recovery.reprompt_validation`.
This module simply re-exports the helpers from the new `validation.py` location.
"""

from .validation import (
    get_validation_function,
    list_validation_functions,
    reprompt_validation,
)

__all__ = [
    "reprompt_validation",
    "get_validation_function",
    "list_validation_functions",
]
