"""``CollectedErrors`` bounds what it remembers, but never the halt.

``_MAX_TRACKED_ERRORS`` exists to cap memory on a mass failure.  The halting
exception is the one thing the next run cannot reconstruct, so it is captured
outside that cap — a halt on the fiftieth file is still a halt.
"""

from __future__ import annotations

from agent_actions.errors import AgentActionsError
from agent_actions.workflow.runner_file_processing import _MAX_TRACKED_ERRORS, CollectedErrors

HALT_TEXT = "Retry exhausted for record abc after 2 attempts (on_exhausted=raise)"


def _halt_error() -> AgentActionsError:
    return AgentActionsError(HALT_TEXT, context={"on_exhausted": "raise"})


class TestTheCapBoundsTheMessagesNotTheHalt:
    """_MAX_TRACKED_ERRORS caps memory; it must not cap the one durable signal."""

    def test_the_halt_is_captured_past_the_cap(self):
        errors = CollectedErrors()
        for i in range(_MAX_TRACKED_ERRORS + 5):
            errors.record(f"f{i}.json", RuntimeError("boom"))

        errors.record("halt.json", _halt_error())

        assert len(errors.messages) == _MAX_TRACKED_ERRORS
        assert errors.halt is not None

    def test_the_first_halt_wins(self):
        errors = CollectedErrors()
        first = _halt_error()

        errors.record("a.json", first)
        errors.record("b.json", _halt_error())

        assert errors.halt is first

    def test_merging_carries_a_halt_from_either_side(self):
        left, right = CollectedErrors(), CollectedErrors()
        right.record("b.json", _halt_error())
        left.record("a.json", RuntimeError("boom"))

        left.merge(right)

        assert left.halt is not None
        assert left.messages == ["a.json: boom", "b.json: " + HALT_TEXT]
