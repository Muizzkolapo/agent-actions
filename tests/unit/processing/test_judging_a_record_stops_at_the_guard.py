"""Judging a record gives the status preparing it would, and stops at the guard.

Batch judges every record its disposition gate carries, as online's guard, which runs
above its gate, judges every record. Preparing one instead would render a prompt that no
batch is sent with.
"""

import pytest

from agent_actions.errors import ConfigurationError, is_action_fatal
from agent_actions.errors.validation import DataValidationError
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.utils.udf_management.registry import udf_tool


def _context(guard=None, source_data=None):
    config = {
        "granularity": "record",
        "context_scope": {"observe": ["a1.n"]},
        "prompt": "Say {{ a1.n }}.",
        "json_mode": False,
    }
    if guard is not None:
        config["guard"] = guard
    return PreparationContext(
        agent_config=config,
        agent_name="a2",
        agent_indices={"a1": 0, "a2": 1},
        source_data=source_data,
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


@pytest.mark.parametrize(
    ("page", "status"), [("kept", GuardStatus.PASSED), ("dropped", GuardStatus.FILTERED)]
)
def test_a_guard_reading_the_source_judges_a_record_as_preparing_it_does(page, status):
    """The record carries no ``source``; only the pool row its guid names does, so the
    guard sees it only through the field context preparing the record builds."""
    reads_the_source = _context(
        _guard('source.page == "kept"', "filter"),
        source_data=[{"source_guid": "G0", "content": {"page": page}}],
    )

    assert TaskPreparer().judge(_record(), reads_the_source) == status
    assert TaskPreparer().prepare(_record(), reads_the_source).guard_status == status


def test_judging_a_record_for_an_action_with_no_guard_resolves_nothing():
    """Batch judges every record it carries; resolving the source for an action with
    no guard would fail the file on a pool row nothing reads for a carried record."""
    unreadable = _context(source_data=[{"source_guid": "G0", "page": "no envelope"}])

    assert TaskPreparer().judge(_record(), unreadable) == GuardStatus.PASSED
    with pytest.raises(DataValidationError):
        TaskPreparer().prepare(_record(), unreadable)


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


def guard_probe_marks_the_seventh_record_seen(data):
    namespace = data["a1"] if "a1" in data else data["content"]["a1"]
    if namespace["n"] == 7:
        namespace["seen"] = True
    return True


def test_a_guard_udf_that_writes_to_any_carried_record_stops_the_action():
    """Judging has no handler that fails one row alone, as preparing the rows sent has, so
    a write on a carried record past the rows batch rehearses before submitting stops the
    action, as online's pre-filter stops it."""
    udf_tool(guard_probe_marks_the_seventh_record_seen)
    config = {
        **_context().agent_config,
        "name": "a2",
        "dependencies": ["a1"],
        "conditional_clause": "guard_probe_marks_the_seventh_record_seen",
    }
    carried = [
        {"source_guid": f"G{n}", "content": {"a1": {"n": n}}, "target_id": f"T{n}"}
        for n in range(1, 8)
    ]

    with pytest.raises(ConfigurationError, match="wrote to its input") as raised:
        BatchTaskPreparator(action_indices={"a1": 0, "a2": 1}).turned_away(config, carried)

    assert is_action_fatal(raised.value)
