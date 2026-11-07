"""A collection credits the guard skips it collected, so the run line can name them."""

import pytest

from agent_actions.processing.disposition_gate import CARRY_FORWARD_REASON
from agent_actions.processing.result_collector import collect_results_from_processing_results
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


def test_guard_skips_are_credited_per_run(backend):
    results = [
        *(ProcessingResult.success(data=_row(f"s{n}"), source_guid=f"s{n}") for n in range(3)),
        ProcessingResult.unprocessed(_row("g1"), GUARD_SKIP, source_guid="g1"),
        ProcessingResult.unprocessed(_row("u1"), UPSTREAM_UNPROCESSED, source_guid="u1"),
    ]

    collect_results_from_processing_results(results, "act", storage_backend=backend)

    assert backend.guard_skips_collected("act") == 1
    assert backend.rows_collected("act") == 5


def test_a_prefilter_skip_is_a_guard_skip(backend):
    results = [ProcessingResult.unprocessed(_row("g1"), GUARD_PREFILTER_SKIP, source_guid="g1")]

    collect_results_from_processing_results(results, "act", storage_backend=backend)

    assert backend.guard_skips_collected("act") == 1


def test_carried_rows_are_not_credited(backend):
    carried = ProcessingResult.unprocessed(_row("g1"), CARRY_FORWARD_REASON, source_guid="g1")

    collect_results_from_processing_results([carried], "act", storage_backend=backend)

    assert backend.guard_skips_collected("act") == 0


def test_two_collections_add_up_and_other_actions_are_apart(backend):
    skip = ProcessingResult.unprocessed(_row("g1"), GUARD_SKIP, source_guid="g1")
    before = backend.guard_skips_collected("act")

    collect_results_from_processing_results([skip], "act", storage_backend=backend)
    collect_results_from_processing_results([skip], "act", storage_backend=backend)

    assert backend.guard_skips_collected("act") - before == 2
    assert backend.guard_skips_collected("other") == 0
