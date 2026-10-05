"""Judging a record gives the status preparing it would, and stops at the guard.

Batch judges every record its disposition gate carries, as online's guard, which runs
above its gate, judges every record. Preparing one instead would render a prompt that no
batch is sent with.
"""

import pytest

from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.processing.task_preparer import TaskPreparer


def _context(guard=None):
    config = {
        "granularity": "record",
        "context_scope": {"observe": ["a1.n"]},
        "prompt": "Say {{ a1.n }}.",
        "json_mode": False,
    }
    if guard is not None:
        config["guard"] = guard
    return PreparationContext(
        agent_config=config, agent_name="a2", agent_indices={"a1": 0, "a2": 1}
    )


def _record(**extra):
    return {"source_guid": "G0", "content": {"a1": {"n": 1}}, **extra}


def _guard(clause, behavior):
    return {"clause": clause, "behavior": behavior, "scope": "item"}


VERDICTS = {
    "no_guard": (None, GuardStatus.PASSED),
    "a_guard_it_passes": (_guard("a1.n == 1", "filter"), GuardStatus.PASSED),
    "a_guard_that_filters_it": (_guard("a1.n == 2", "filter"), GuardStatus.FILTERED),
    "a_guard_that_skips_it": (_guard("a1.n == 2", "skip"), GuardStatus.SKIPPED),
    "a_guard_that_only_warns": (_guard("a1.n == 2", "warn"), GuardStatus.PASSED),
}


@pytest.mark.parametrize(("guard", "status"), VERDICTS.values(), ids=VERDICTS.keys())
def test_judging_a_record_gives_the_status_preparing_it_gives(guard, status):
    assert TaskPreparer().judge(_record(), _context(guard)) == status
    assert TaskPreparer().prepare(_record(), _context(guard)).guard_status == status


def test_a_record_the_action_above_blocked_is_not_put_to_the_guard():
    """Preparing it does not reach the guard either."""
    blocked = _record(_state="failed")
    turns_everything_away = _context(_guard("a1.n == 2", "filter"))

    assert TaskPreparer().judge(blocked, turns_everything_away) == (
        GuardStatus.UPSTREAM_UNPROCESSED
    )
    assert TaskPreparer().prepare(blocked, turns_everything_away).guard_status == (
        GuardStatus.UPSTREAM_UNPROCESSED
    )


def test_judging_a_record_the_guard_passes_renders_no_prompt(monkeypatch):
    def rendered(*args, **kwargs):
        raise AssertionError("a prompt was rendered")

    monkeypatch.setattr(TaskPreparer, "_render_prompt", staticmethod(rendered))

    assert TaskPreparer().judge(_record(), _context(_guard("a1.n == 1", "filter"))) == (
        GuardStatus.PASSED
    )
