"""A parent with a live recovery child is not reprocessed.

This is the invariant that makes registration safe to sweep every sibling entry
for a parent: nothing can register a second live recovery for the same parent,
because the parent itself is skipped for the whole pass while one exists.
"""

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services.processing import _superseded_entries

PARENT = "pages.json"


def _entry(name, status, parent=None, kind=None, attempt=0, ts="2026-04-20T00:00:00Z"):
    return BatchJobEntry(
        batch_id=f"b-{name}",
        status=status,
        timestamp=ts,
        provider="openai",
        record_count=1,
        file_name=name,
        parent_file_name=parent,
        recovery_type=kind,
        recovery_attempt=attempt,
    )


def _jobs(*entries):
    return {e.file_name: e for e in entries}


def test_a_parent_with_a_live_repair_child_is_superseded():
    jobs = _jobs(
        _entry(PARENT, BatchStatus.COMPLETED),
        _entry(f"{PARENT}_repair_1", BatchStatus.SUBMITTED, PARENT, "repair", 1),
    )
    assert PARENT in _superseded_entries(jobs), (
        "the parent would be reprocessed while its repair round is still running, "
        "and the reprompt it starts would sweep that round's registry entry away"
    )


def test_a_parent_with_a_live_reprompt_child_is_superseded():
    jobs = _jobs(
        _entry(PARENT, BatchStatus.COMPLETED),
        _entry(f"{PARENT}_reprompt_1", BatchStatus.SUBMITTED, PARENT, "reprompt", 1),
    )
    assert PARENT in _superseded_entries(jobs)


def test_a_parent_with_a_completed_child_is_superseded():
    jobs = _jobs(
        _entry(PARENT, BatchStatus.COMPLETED),
        _entry(f"{PARENT}_repair_1", BatchStatus.COMPLETED, PARENT, "repair", 1),
    )
    assert PARENT in _superseded_entries(jobs)


def test_a_parent_with_no_child_is_processed():
    jobs = _jobs(_entry(PARENT, BatchStatus.COMPLETED))
    assert _superseded_entries(jobs) == set()


def test_the_live_child_itself_is_not_superseded():
    child = f"{PARENT}_repair_1"
    jobs = _jobs(
        _entry(PARENT, BatchStatus.COMPLETED),
        _entry(child, BatchStatus.SUBMITTED, PARENT, "repair", 1),
    )
    assert child not in _superseded_entries(jobs), "the round that is actually running was skipped"
