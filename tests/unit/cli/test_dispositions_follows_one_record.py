"""`agac dispositions --record ID` follows one record through every action, in run order.

Each action shows the record's disposition and reason, or that the record never reached
it; a guard that filtered or skipped it, or sent it to another branch, is named.
"""

from __future__ import annotations

import pytest

from agent_actions.cli.dispositions import record_trail
from agent_actions.record.reasons import EXPECTATIONS_FAILED, GUARD_FILTER, SENT_ELSEWHERE
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

WORKFLOW = "wf"
ORDER = ["read", "classify", "route_a", "route_b", "reply"]
CONFIGS = {
    "classify": {"guard": {"clause": "read.is_spam == false"}},
    "route_b": {"guard": {"clause": 'classify.queue == "b"'}},
}


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store" / f"{WORKFLOW}.db"), WORKFLOW)
    store.initialize()
    yield store
    store.close()


def _step(trail: dict, action: str) -> dict:
    return next(step for step in trail["actions"] if step["name"] == action)


def test_a_record_dropped_by_a_guard_names_the_guard_and_reaches_nothing_after(backend):
    backend.set_disposition("read", "spam", "success")
    backend.set_disposition("classify", "spam", "filtered", reason=GUARD_FILTER)

    trail = record_trail(backend, WORKFLOW, "spam", ORDER, CONFIGS)

    assert (trail["reached"], trail["last"]) == (2, "classify")
    assert _step(trail, "classify") == {
        "name": "classify",
        "disposition": "filtered",
        "reason": GUARD_FILTER,
        "detail": None,
        "guard": "read.is_spam == false",
    }
    assert [step["disposition"] for step in trail["actions"][2:]] == [None, None, None]


def test_a_record_routed_away_is_sent_elsewhere_with_the_route_s_guard(backend):
    for action in ("read", "classify", "route_a", "reply"):
        backend.set_disposition(action, "r1", "success")
    backend.set_disposition("route_b", "r1", "filtered", reason=SENT_ELSEWHERE)

    trail = record_trail(backend, WORKFLOW, "r1", ORDER, CONFIGS)

    assert _step(trail, "route_b")["disposition"] == "sent_elsewhere"
    assert _step(trail, "route_b")["guard"] == 'classify.queue == "b"'
    assert (trail["reached"], trail["last"]) == (5, "reply")


def test_a_shipped_record_whose_checks_failed_reads_as_failed_checks(backend):
    backend.set_disposition("read", "r1", "success", reason=EXPECTATIONS_FAILED)

    trail = record_trail(backend, WORKFLOW, "r1", ["read"], {})

    assert _step(trail, "read")["disposition"] == "failed_checks"
    assert _step(trail, "read")["guard"] is None


def test_a_failure_keeps_its_reason_and_names_no_guard(backend):
    backend.set_disposition("classify", "r1", "failed", reason="timeout", detail="after 3 tries")

    step = _step(record_trail(backend, WORKFLOW, "r1", ORDER, CONFIGS), "classify")

    assert (step["disposition"], step["reason"], step["detail"], step["guard"]) == (
        "failed",
        "timeout",
        "after 3 tries",
        None,
    )


def test_a_record_no_action_holds_reaches_nothing(backend):
    trail = record_trail(backend, WORKFLOW, "nope", ORDER, CONFIGS)

    assert (trail["reached"], trail["last"]) == (0, None)
