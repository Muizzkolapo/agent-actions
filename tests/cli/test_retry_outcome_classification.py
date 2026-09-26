"""`agac retry` and `agac run` decide a finished workflow the same way.

Both feed the answer to the run tracker and to an exit code, so a repair loop
reading one command's result reads the other's. The table below is `run.py`'s
classification, written out; retry's drifted from it on the paused case while
retry ignored its own answer, which would have become an exit-code difference
between the two commands as soon as it stopped.
"""

import pytest

from agent_actions.cli.retry import _classify_outcome


class FakeStateManager:
    def __init__(self, complete: bool, done: bool, any_failed: bool):
        self._complete = complete
        self._done = done
        self._any_failed = any_failed

    def is_workflow_complete(self) -> bool:
        return self._complete

    def is_workflow_done(self) -> bool:
        return self._done

    def has_any_failed(self) -> bool:
        return self._any_failed


# (complete, done, any_failed) -> the status run.py assigns
RUN_CLASSIFICATION = [
    (True, True, False, "SUCCESS"),
    (True, True, True, "SUCCESS"),
    (False, True, True, "FAILED"),
    (False, True, False, "SUCCESS"),
    (False, False, False, "PAUSED"),
    (False, False, True, "PAUSED"),
]


@pytest.mark.parametrize(("complete", "done", "any_failed", "expected"), RUN_CLASSIFICATION)
def test_it_matches_run(complete, done, any_failed, expected):
    assert _classify_outcome(FakeStateManager(complete, done, any_failed)) == expected


def test_an_unfinished_workflow_is_not_a_failure():
    """The case retry got wrong: actions still to run is paused, not failed."""
    assert _classify_outcome(FakeStateManager(complete=False, done=False, any_failed=False)) != (
        "FAILED"
    )


def test_a_completed_action_holding_failed_records_is_a_success():
    """``completed_with_failures`` counts as complete, so the record-level
    failures inside it do not make the command exit non-zero."""
    assert _classify_outcome(FakeStateManager(complete=True, done=True, any_failed=True)) == (
        "SUCCESS"
    )


def test_a_failed_action_is_the_only_failure():
    assert _classify_outcome(FakeStateManager(complete=False, done=True, any_failed=True)) == (
        "FAILED"
    )
