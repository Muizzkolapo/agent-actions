"""Declare and detect errors that are fatal to a whole action."""

from agent_actions.errors.base import enrich_exception_context, raised_by_exhaustion_policy

_ACTION_FATAL_KEY = "action_fatal"


def mark_action_fatal(error: Exception) -> Exception:
    """Declare *error* an indictment of the action's contract, not of one input.

    Tags in place and returns the same error, so a re-raise can mark and then
    ``raise`` bare, keeping the original traceback.
    """
    enrich_exception_context(error, **{_ACTION_FATAL_KEY: True})
    return error


def is_action_fatal(error: BaseException) -> bool:
    """True if some layer declared *error* fatal to the action.

    Fatality is declared where it is known — the processing loops that
    deliberately re-raise instead of tombstoning — and never inferred from the
    type here: the layers above wrap on the way up, so an error's outermost
    type says only who caught it last. The chain is searched for the same
    reason ``raised_by_exhaustion_policy`` searches it.
    """
    from agent_actions.utils.safe_format import get_error_chain

    if raised_by_exhaustion_policy(error):
        return True
    if not isinstance(error, Exception):
        return False
    for link in get_error_chain(error):
        context = getattr(link, "context", None)
        if isinstance(context, dict) and context.get(_ACTION_FATAL_KEY) is True:
            return True
    return False
