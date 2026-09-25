"""ErrorContextService.merge_exception_context must honor __suppress_context__.

Same bug shape as extract_root_cause (see spec 626): the chain walk followed
__context__ unconditionally, so a suppressed exception's .context dict still
leaked into the merged context shown to the user.
"""

from agent_actions.logging.errors.services.context import ErrorContextService


def test_raise_from_none_stops_context_merge_at_the_suppressing_exception():
    suppressed_away = ValueError("hidden interpreter noise")
    suppressed_away.context = {"leaked": "yes"}

    try:
        try:
            raise suppressed_away
        except ValueError:
            raise RuntimeError("the deliberate, user-facing error") from None
    except RuntimeError as caught:
        deliberate = caught
        deliberate.context = {"deliberate": "kept"}

    merged = ErrorContextService.merge_exception_context(deliberate)

    assert merged.get("deliberate") == "kept"
    assert "leaked" not in merged
