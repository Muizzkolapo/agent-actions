"""What is not a guard skip collected this run is not credited as one."""

import pytest

from agent_actions.processing.disposition_gate import CARRY_FORWARD_REASON
from agent_actions.processing.result_collector import collect_results_from_processing_results
from agent_actions.processing.types import ProcessingResult
from agent_actions.record.reasons import GUARD_FILTER, GUARD_SKIP
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    yield store
    store.close()


def _row(guid: str, **extra) -> list[dict]:
    return [{"source_guid": guid, "content": {"act": {"a": 1}}, **extra}]


def test_a_carried_guard_skip_tombstone_is_not_credited_beside_a_new_skip(backend):
    carried = ProcessingResult.unprocessed(
        _row("old", _state="guard_skipped", _reason=GUARD_SKIP), GUARD_SKIP, source_guid="old"
    )
    carried.skip_reason = CARRY_FORWARD_REASON
    new = ProcessingResult.unprocessed(_row("new"), GUARD_SKIP, source_guid="new")

    collect_results_from_processing_results([carried, new], "act", storage_backend=backend)

    assert backend.guard_skips_collected("act") == 1


def test_a_filtered_record_is_not_a_guard_skip(backend):
    filtered = ProcessingResult.filtered(source_guid="f1")
    filtered.skip_reason = GUARD_FILTER
    skip = ProcessingResult.unprocessed(_row("g1"), GUARD_SKIP, source_guid="g1")

    collect_results_from_processing_results([filtered, skip], "act", storage_backend=backend)

    assert backend.guard_skips_collected("act") == 1


def test_take_returns_the_tally_once(backend):
    backend.credit_guard_skips("act", 2)

    assert (backend.take_guard_skips("act"), backend.take_guard_skips("act")) == (2, 0)
    assert backend.guard_skips_collected("act") == 0
