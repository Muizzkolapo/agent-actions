"""Declare and detect errors that are fatal to a whole action."""

from agent_actions.errors.base import enrich_exception_context, raised_by_exhaustion_policy

_ACTION_FATAL_KEY = "action_fatal"
_EVERY_FILE_FAILED_KEY = "every_file_failed"
_EVERY_RECORD_FAILED_KEY = "every_record_failed"
_SUBMISSION_REFUSED_KEY = "submission_refused"


def mark_action_fatal(error: Exception) -> Exception:
    """Declare *error* fatal to the whole action, not to the one input it was raised for.

    Tags in place and returns the same error, so a re-raise can mark and then
    ``raise`` bare, keeping the original traceback.
    """
    enrich_exception_context(error, **{_ACTION_FATAL_KEY: True})
    return error


def is_action_fatal(error: BaseException) -> bool:
    """True if some layer declared *error* fatal to the action.

    Fatality is declared where it is known and never inferred from the type
    here: the layers above wrap on the way up, so an error's outermost type
    says only who caught it last. The chain is searched for the same reason
    ``raised_by_exhaustion_policy`` searches it. A path that declares nothing
    keeps its failures per-item.
    """
    if raised_by_exhaustion_policy(error):
        return True
    return _declared(error, _ACTION_FATAL_KEY)


def mark_submission_refused(error: Exception) -> Exception:
    """Declare *error* a batch the provider did not take, so nothing was sent or stored.

    Tags in place and returns the same error, as ``mark_action_fatal`` does.
    """
    enrich_exception_context(error, **{_SUBMISSION_REFUSED_KEY: True})
    return error


def is_submission_refused(error: BaseException) -> bool:
    """True if *error*, or anything it chains to, is a batch the provider did not take."""
    return _declared(error, _SUBMISSION_REFUSED_KEY)


def mark_every_file_failed(error: Exception) -> Exception:
    """Declare that *error* ends a pass that reached every record of every input file
    and failed each one, with nothing fatal to the action among them."""
    enrich_exception_context(error, **{_EVERY_FILE_FAILED_KEY: True})
    return error


def every_file_failed(error: BaseException) -> bool:
    """True if *error*, or anything it chains to, was declared by ``mark_every_file_failed``."""
    return _declared(error, _EVERY_FILE_FAILED_KEY)


def mark_every_record_failed(error: Exception) -> Exception:
    """Declare that *error* ends one input file after every record in it was reached and
    failed, unlike an error that stops the file partway."""
    enrich_exception_context(error, **{_EVERY_RECORD_FAILED_KEY: True})
    return error


def every_record_failed(error: BaseException) -> bool:
    """True if *error*, or anything it chains to, was declared by ``mark_every_record_failed``."""
    return _declared(error, _EVERY_RECORD_FAILED_KEY)


def _declared(error: BaseException, key: str) -> bool:
    from agent_actions.utils.safe_format import get_error_chain

    if not isinstance(error, Exception):
        return False
    return any(
        isinstance(getattr(link, "context", None), dict) and link.context.get(key) is True
        for link in get_error_chain(error)
    )
