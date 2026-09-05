"""Resetting the global guard filter must not leave stale references behind.

`reset_global_guard_filter()` is a testing utility that shuts the filter's
thread pool down. A second singleton — the guard *evaluator* — caches the filter
it was built with, so a reset that clears only the filter leaves the evaluator
holding a pool nobody can submit to again.
"""

from agent_actions.input.preprocessing.filtering.evaluator import get_guard_evaluator
from agent_actions.input.preprocessing.filtering.guard_filter import (
    get_global_guard_filter,
    reset_global_guard_filter,
)


class TestResetDropsCachedReferences:
    def teardown_method(self):
        reset_global_guard_filter()

    def test_the_evaluator_does_not_survive_holding_a_dead_filter(self):
        get_global_guard_filter()
        first = get_guard_evaluator()
        assert first._filter.executor._shutdown is False

        reset_global_guard_filter()

        refreshed = get_guard_evaluator()
        assert refreshed._filter.executor._shutdown is False, (
            "the evaluator singleton is still holding the filter that reset shut down"
        )
