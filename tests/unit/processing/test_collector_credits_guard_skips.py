"""A collection counts the guard skips it collected, so the run line can name them."""

import pytest

from agent_actions.processing.disposition_gate import CARRY_FORWARD_REASON
from agent_actions.processing.result_collector import collect_results_from_processing_results
from agent_actions.processing.run_counts import counting
from agent_actions.processing.types import ProcessingResult
from agent_actions.record.reasons import GUARD_PREFILTER_SKIP, GUARD_SKIP, UPSTREAM_UNPROCESSED
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    yield store
    store.close()


def _row(guid: str) -> list[dict]:
    return [{"source_guid": guid, "content": {"act": {"a": 1}}}]


def test_guard_skips_are_counted_on_the_collection(backend):
    results = [
        *(ProcessingResult.success(data=_row(f"s{n}"), source_guid=f"s{n}") for n in range(3)),
        ProcessingResult.unprocessed(_row("g1"), GUARD_SKIP, source_guid="g1"),
        ProcessingResult.unprocessed(_row("u1"), UPSTREAM_UNPROCESSED, source_guid="u1"),
    ]

    _, stats = collect_results_from_processing_results(results, "act", storage_backend=backend)

    assert stats.guard_skipped == 1
    assert backend.rows_collected("act") == 5


def test_a_prefilter_skip_is_a_guard_skip(backend):
    results = [ProcessingResult.unprocessed(_row("g1"), GUARD_PREFILTER_SKIP, source_guid="g1")]

    _, stats = collect_results_from_processing_results(results, "act", storage_backend=backend)

    assert stats.guard_skipped == 1


def test_carried_rows_are_not_counted(backend):
    carried = ProcessingResult.unprocessed(_row("g1"), CARRY_FORWARD_REASON, source_guid="g1")

    _, stats = collect_results_from_processing_results([carried], "act", storage_backend=backend)

    assert stats.guard_skipped == 0


def test_two_collections_in_one_execution_add_up_and_others_are_apart(backend):
    skip = ProcessingResult.unprocessed(_row("g1"), GUARD_SKIP, source_guid="g1")
    collect_results_from_processing_results([skip], "act", storage_backend=backend)

    with counting() as first:
        collect_results_from_processing_results([skip], "act", storage_backend=backend)
        collect_results_from_processing_results([skip], "act", storage_backend=backend)
    with counting() as second:
        pass

    assert first.guard_skipped == 2
    assert second.guard_skipped == 0
