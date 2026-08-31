"""Classify errors as action-fatal or per-item recoverable."""

from agent_actions.errors.base import raised_by_exhaustion_policy
from agent_actions.errors.configuration import ConfigurationError, RecordContextError
from agent_actions.errors.operations import TemplateVariableError
from agent_actions.errors.processing import EmptyOutputError
from agent_actions.errors.validation import SchemaValidationError


def is_action_fatal(error: BaseException) -> bool:
    """True for errors that indict the action's contract rather than one input.

    Mirrors what the processing strategies deliberately re-raise out of their
    per-record loops: an ``on_exhausted: raise`` halt, configuration errors
    (except the per-record ``RecordContextError``), empty-output and
    schema-validation failures, and a template broken by syntax rather than by
    one record's missing variables. Everything else is an accident of one
    input and stays tolerated where it happened.
    """
    if raised_by_exhaustion_policy(error):
        return True
    if isinstance(error, RecordContextError):
        return False
    if isinstance(error, TemplateVariableError):
        return not error.missing_variables
    return isinstance(error, (ConfigurationError, EmptyOutputError, SchemaValidationError))
