"""Online collection writes a disposition before the file only when it vouches for no row.

What the gate carries a record from the stored file by waits until the file is stored:
written before it, a run stopped in between left records marked done while the stored file
held an earlier run's rows. Everything else is written at once, since a file in which every
record failed or was exhausted is left unwritten while its stored answers stand, and `agac
retry` reads the failures and a fan-in reads the filter.
"""

import pytest

from agent_actions.processing.result_collector import collect_results_from_processing_results
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "summarize"


@pytest.fixture
def backend(tmp_path):
    db = SQLiteBackend.create(db_path=str(tmp_path / "store.db"), workflow_name="wf")
    db.initialize()
    yield db
    db.close()


def _one_of_each():
    return [
        ProcessingResult.success(
            data=[{"source_guid": "answered", "content": {ACTION: {"summary": "s"}}}],
            source_guid="answered",
        ),
        ProcessingResult.skipped(
            passthrough_data={"source_guid": "passed"}, reason="guard_skip", source_guid="passed"
        ),
        ProcessingResult.filtered(source_guid="filtered"),
        ProcessingResult.failed(error="boom", source_guid="failed"),
        ProcessingResult.exhausted(error="spent", source_guid="exhausted"),
        ProcessingResult.unprocessed(
            data=[{"source_guid": "upstream"}], reason="upstream_failed", source_guid="upstream"
        ),
        ProcessingResult.deferred(task_id="t1", source_guid="queued"),
    ]


def test_online_collection_holds_back_only_what_the_gate_carries_from_the_file(backend):
    context = ProcessingContext(
        agent_config={}, agent_name=ACTION, storage_backend=backend, defer_kept_dispositions=True
    )

    collect_results_from_processing_results(
        _one_of_each(), ACTION, storage_backend=backend, context=context
    )

    written = {row["record_id"]: row["disposition"] for row in backend.get_disposition(ACTION)}
    assert written == {
        "filtered": "filtered",
        "failed": "failed",
        "exhausted": "exhausted",
        "upstream": "unprocessed",
        "queued": "deferred",
    }
    assert {row[1]: row[2] for row in context.kept_dispositions} == {
        "answered": "success",
        "passed": "passthrough",
    }


def test_a_batch_collect_writes_every_disposition_at_once(backend):
    """Batch marks a file collected only after writing it, so a collect pass stopped
    before the write collects that file again."""
    context = ProcessingContext(agent_config={}, agent_name=ACTION, storage_backend=backend)

    collect_results_from_processing_results(
        _one_of_each(), ACTION, storage_backend=backend, context=context
    )

    assert len(backend.get_disposition(ACTION)) == 7
    assert context.kept_dispositions == []
